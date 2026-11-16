"""Admin-only diagnostics: GET /api/probe?key=ADMIN_KEY&u=<url>
Shows what the bot can extract for a link (Instagram media list, YouTube client results)
without sending anything to Telegram."""
import json, os, sys, tempfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import requests
import core, ig


def is_admin(key):
    try:
        # linkster_stats checks the admin key server-side and refuses anything else
        r = requests.post(f"{os.environ['SUPABASE_URL']}/rest/v1/rpc/linkster_stats", timeout=10,
                          headers={"apikey": os.environ["SUPABASE_KEY"], "Content-Type": "application/json"},
                          json={"p_key": key, "p_days": 1})
        return r.status_code == 200
    except Exception:
        return False


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        if not is_admin(q.get("key", [""])[0]):
            self.send_response(403); self.end_headers(); return
        url, kind = core.clean_url(q.get("u", [""])[0])
        out = {"url": url, "kind": kind}
        if kind == "ig":
            try:
                core.tools()
                res = ig.fetch(url, core.cookies_file(), core.ydl_opts(Path(tempfile.mkdtemp(dir=core.TMP))))
                out["ig"] = {"owner": res["owner"], "n": len(res["items"]),
                             "items": [{"type": i["type"], "w": i.get("w"), "h": i.get("h"), "url": i["url"][:90]} for i in res["items"]]}
            except ig.IGError as e:
                out["ig_error"] = {"key": e.key, "detail": e.detail}
        if kind and q.get("ytdlp", ["1"])[0] == "1":
            core.tools()
            ladder = core.CLIENT_LADDER if kind == "yt" else [None]
            for c in ladder:
                try:
                    info = core.probe(url, Path(tempfile.mkdtemp(dir=core.TMP)), c)
                    out[f"ytdlp {c}"] = f"OK {info.get('title')} formats={len(info.get('formats') or [])}"
                    break
                except Exception as e:
                    out[f"ytdlp {c}"] = "ERR " + str(e)[:300]
        b = json.dumps(out, ensure_ascii=False, indent=1).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)
