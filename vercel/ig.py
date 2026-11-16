"""Instagram post media without yt-dlp: photos, carousels and videos.

Two public, login-free sources are tried in order, then the same with cookies when
COOKIES_B64 holds an instagram.com session:
  1. the web GraphQL endpoint (the one instagram.com itself calls for a post);
  2. the /embed/captioned/ page, which carries the same media JSON for public posts.
Returns {"items": [{"type": "photo"|"video", "url", "w", "h"}...], "caption", "owner"} or raises IGError.
"""
import html, json, re
from http.cookiejar import MozillaCookieJar

import requests

SC_RE = re.compile(r"instagram\.com/(?:[A-Za-z0-9_.]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]{5,})")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
APP_ID = "936619743392459"
DOC_ID = "8845758582119845"


class IGError(Exception):
    def __init__(self, key, detail=""):
        super().__init__(f"{key}: {detail}")
        self.key, self.detail = key, detail


def shortcode(url):
    m = SC_RE.search(url or "")
    return m.group(1) if m else None


def _session(cookie_path=None):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    if cookie_path:
        try:
            jar = MozillaCookieJar(cookie_path)
            jar.load(ignore_discard=True, ignore_expires=True)
            for c in jar:
                if "instagram.com" in c.domain:
                    s.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
        except Exception:
            pass
    return s


def _logged_in(s):
    return any(c.name == "sessionid" for c in s.cookies)


def _items_from_node(node):
    """xdt_shortcode_media / shortcode_media -> items."""
    def one(n):
        if n.get("is_video") and n.get("video_url"):
            d = n.get("dimensions") or {}
            return {"type": "video", "url": n["video_url"], "w": d.get("width"), "h": d.get("height"),
                    "thumb": n.get("display_url")}
        res = n.get("display_resources") or []
        best = max(res, key=lambda r: r.get("config_width") or 0)["src"] if res else n.get("display_url")
        d = n.get("dimensions") or {}
        return {"type": "photo", "url": best, "w": d.get("width"), "h": d.get("height")} if best else None

    kids = ((node.get("edge_sidecar_to_children") or {}).get("edges")) or []
    items = [one(e.get("node") or {}) for e in kids] if kids else [one(node)]
    items = [i for i in items if i]
    cap = ""
    try:
        cap = node["edge_media_to_caption"]["edges"][0]["node"]["text"]
    except Exception:
        pass
    owner = (node.get("owner") or {}).get("username") or ""
    return {"items": items, "caption": cap, "owner": owner}


def _graphql(s, sc):
    h = {"X-IG-App-ID": APP_ID, "X-ASBD-ID": "129477", "X-IG-WWW-Claim": "0", "X-Requested-With": "XMLHttpRequest",
         "Origin": "https://www.instagram.com", "Referer": f"https://www.instagram.com/p/{sc}/",
         "Content-Type": "application/x-www-form-urlencoded", "Accept": "*/*"}
    csrf = s.cookies.get("csrftoken")
    if csrf:
        h["X-CSRFToken"] = csrf
    r = s.post("https://www.instagram.com/graphql/query/", headers=h, timeout=15,
               data={"doc_id": DOC_ID, "variables": json.dumps({"shortcode": sc, "fetch_tagged_user_count": None,
                                                                "hoisted_comment_id": None, "hoisted_reply_id": None})})
    if r.status_code != 200 or not r.text.lstrip().startswith("{"):
        raise IGError("blocked", f"graphql http {r.status_code}")
    data = (r.json().get("data") or {})
    node = data.get("xdt_shortcode_media") or data.get("shortcode_media")
    if not node:
        raise IGError("private", "graphql: no media (private, removed or login wall)")
    return _items_from_node(node)


def _embed(s, sc):
    r = s.get(f"https://www.instagram.com/p/{sc}/embed/captioned/", timeout=15,
              headers={"Referer": "https://www.instagram.com/"})
    if r.status_code != 200:
        raise IGError("blocked", f"embed http {r.status_code}")
    t = r.text
    # newer embeds carry the full media node as escaped JSON inside a script
    m = re.search(r'\\"shortcode_media\\":(\{.*?\}),\\"(?:viewer|preview)', t) or None
    for blob in re.findall(r'"contextJSON":"((?:[^"\\]|\\.)*)"', t):
        try:
            ctx = json.loads(json.loads(f'"{blob}"'))
            node = (ctx.get("gql_data") or {}).get("shortcode_media") or ctx.get("context", {}).get("media")
            if node:
                return _items_from_node(node)
        except Exception:
            continue
    # fallback: single image / video tags rendered in the embed
    vids = re.findall(r'"video_url":"([^"]+)"', t)
    if vids:
        return {"items": [{"type": "video", "url": json.loads(f'"{vids[0]}"')}], "caption": "", "owner": ""}
    imgs = re.findall(r'class="EmbeddedMediaImage"[^>]*src="([^"]+)"', t) or re.findall(r'<img[^>]+class="EmbeddedMediaImage"[^>]+src="([^"]+)"', t)
    if imgs:
        return {"items": [{"type": "photo", "url": html.unescape(imgs[0])}], "caption": "", "owner": ""}
    if "is_video" in t and "video_url" not in t:
        raise IGError("login", "embed: video hidden without login")
    raise IGError("private", "embed: no media found")


def _best(cands, key="width"):
    cands = [c for c in (cands or []) if c.get("url")]
    return max(cands, key=lambda c: c.get(key) or 0) if cands else None


def _items_from_product(p):
    """Instagram API media item (as yt-dlp receives it) -> items."""
    def one(m):
        v = _best(m.get("video_versions"))
        img = _best((m.get("image_versions2") or {}).get("candidates"))
        if v:
            return {"type": "video", "url": v["url"], "w": v.get("width"), "h": v.get("height"),
                    "thumb": img and img["url"]}
        if img:
            return {"type": "photo", "url": img["url"], "w": img.get("width"), "h": img.get("height")}
        return None
    kids = p.get("carousel_media") or []
    items = [i for i in (one(m) for m in (kids or [p])) if i]
    return {"items": items, "caption": ((p.get("caption") or {}).get("text") or ""),
            "owner": ((p.get("user") or {}).get("username") or "")}


def _ytdlp(url, ydl_params):
    """Let yt-dlp's Instagram extractor do the hard part (tokens, cookies, fallbacks) and keep the raw
    media it found, instead of letting it fail with 'There is no video in this post' on photos."""
    import yt_dlp
    from yt_dlp.extractor.instagram import InstagramIE
    got = {}

    class Capture(InstagramIE):
        def _extract_product(self, product_info, video_id=None, get_comments=True):
            got["p"] = product_info[0] if isinstance(product_info, list) else product_info
            return {"id": video_id or "x", "formats": [{"url": "https://example.invalid/x.mp4"}]}

    with yt_dlp.YoutubeDL({**ydl_params, "skip_download": True}) as y:
        ie = Capture(y)
        try:
            ie.extract(url)
        except Exception as e:
            if "p" not in got:
                raise IGError("login" if "login" in str(e).lower() or "empty media" in str(e).lower() else "private",
                              f"yt-dlp: {str(e)[:250]}")
    if "p" not in got:
        raise IGError("private", "yt-dlp: no media")
    return _items_from_product(got["p"])


def fetch(url, cookie_path=None, ydl_params=None):
    sc = shortcode(url)
    if not sc:
        raise IGError("unsupported", "not a post/reel link")
    errs = []
    if ydl_params is not None:
        try:
            res = _ytdlp(url, ydl_params)
            if res["items"]:
                res["shortcode"] = sc
                return res
        except IGError as e:
            errs.append(e.detail)
        except Exception as e:
            errs.append(f"yt-dlp: {repr(e)[:200]}")
    sessions = [_session()]
    if cookie_path:
        s2 = _session(cookie_path)
        if _logged_in(s2):
            sessions.append(s2)
    for s in sessions:
        for fn in (_graphql, _embed):
            try:
                res = fn(s, sc)
                if res["items"]:
                    res["shortcode"] = sc
                    return res
            except IGError as e:
                errs.append(f"{fn.__name__}{'+cookies' if _logged_in(s) else ''}: {e.detail}")
            except Exception as e:
                errs.append(f"{fn.__name__}: {repr(e)[:150]}")
    key = "login" if any("login" in e or "http 4" in e for e in errs) else "private"
    raise IGError(key, " | ".join(errs))


def download(item, path, max_bytes):
    """Stream one media file to path; returns size. Raises IGError('too_big')."""
    with requests.get(item["url"], stream=True, timeout=30, headers={"User-Agent": UA, "Referer": "https://www.instagram.com/"}) as r:
        r.raise_for_status()
        n = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                n += len(chunk)
                if n > max_bytes:
                    raise IGError("too_big", f"{n} bytes")
                f.write(chunk)
    return n
