"""Linkster serverless core: Telegram helpers + yt-dlp download with fallbacks. No state is kept."""
import sys
import base64, hashlib, http.client, json, os, re, shutil, stat, subprocess, tempfile, time
from pathlib import Path
from urllib.parse import urlparse

import requests

TOKEN = os.environ["BOT_TOKEN"]
SECRET = hashlib.sha256(("linkster:" + TOKEN).encode()).hexdigest()[:40]  # webhook + worker auth
API = f"https://api.telegram.org/bot{TOKEN}"
MAX_BYTES = 49 * 1024 * 1024
MAX_DURATION = 60 * 60
DEADLINE = 270  # seconds, Vercel limit is 300
HERE = Path(__file__).parent
TMP = Path(tempfile.gettempdir())

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
ALLOWED = {"youtube.com": "yt", "m.youtube.com": "yt", "music.youtube.com": "yt", "youtu.be": "yt",
           "youtube-nocookie.com": "yt", "instagram.com": "ig", "instagr.am": "ig"}

T = {
    "ru": {
        "start": ("👋 <b>Привет!</b>\n\nПришли ссылку на видео из <b>YouTube</b> или <b>Instagram</b> "
                  "(Reels, посты, Shorts), и я пришлю файл в <b>MP4</b> или <b>MP3</b>.\n\n"
                  "Лимит Telegram для ботов — 50 МБ: длинные видео сжимаются по качеству.\n"
                  "Я ничего не храню у себя: файл остаётся только в этом чате — перешли его куда нужно."),
        "choose": "Что скачать?", "mp4": "🎬 MP4 (видео)", "mp3": "🎵 MP3 (звук)",
        "no_url": "🔗 Пришли ссылку на YouTube или Instagram.",
        "bad_host": "😕 Поддерживаются только ссылки YouTube и Instagram.",
        "expired": "⌛ Ссылка не найдена, отправь её ещё раз.",
        "queue": "⏳ В очереди…", "checking": "🔎 Проверяю ссылку…", "download": "⬇️ Скачиваю…",
        "retry": "🔁 Пробую другой способ…", "upload": "📤 Отправляю…",
        "too_long": "⛔ Видео длиннее {m} мин — слишком большое для бота. Попробуй MP3.",
        "too_big": "⛔ Не уложился в лимит 50 МБ даже в минимальном качестве. Попробуй MP3.",
        "live": "⛔ Прямые эфиры не поддерживаются.",
        "private": "🔒 Видео недоступно: оно приватное или удалено.",
        "no_video": "📷 В этом посте нет видео, только фото. Пришли ссылку на Reels или пост с видео.",
        "age": "🔞 У видео возрастное ограничение: YouTube отдаёт его только аккаунтам 18+. Скачать не получится.",
        "geo": "🌍 Видео закрыто для страны, где стоит сервер бота. Скачать не получится.",
        "login": "🔐 {svc} не отдал видео без входа в аккаунт. Обычно это временно: попробуй через 10–15 минут.",
        "blocked": "🚧 Сервис блокирует загрузку с сервера. Попробуй через несколько минут.",
        "timeout": "⏱ Не успел обработать за отведённое время. Попробуй MP3 или более короткое видео.",
        "fail": "❌ Не получилось скачать. Проверь ссылку и попробуй ещё раз.",
        "credit": "Скачано с помощью @linkster_bot",
        "fallback_mp3": "📦 Видео не помещается в лимит Telegram для ботов (50 МБ), присылаю звук в MP3.",
        "photo_only_mp3": "🖼 В этом посте нет звука, только фото. Присылаю фото.",
        "skipped": "⚠️ Часть файлов больше 50 МБ, их Telegram не даёт отправить ботам: {n} шт.",
    },
    "uz": {
        "start": ("👋 <b>Salom!</b>\n\n<b>YouTube</b> yoki <b>Instagram</b> (Reels, post, Shorts) havolasini yuboring — "
                  "men uni <b>MP4</b> yoki <b>MP3</b> qilib yuboraman.\n\n"
                  "Telegram botlar uchun limit — 50 MB: uzun videolar sifati pasaytiriladi.\n"
                  "Men hech narsa saqlamayman: fayl faqat shu chatda qoladi — kerakli joyga yuboring."),
        "choose": "Nimani yuklab olay?", "mp4": "🎬 MP4 (video)", "mp3": "🎵 MP3 (ovoz)",
        "no_url": "🔗 YouTube yoki Instagram havolasini yuboring.",
        "bad_host": "😕 Faqat YouTube va Instagram havolalari qo'llab-quvvatlanadi.",
        "expired": "⌛ Havola topilmadi, qayta yuboring.",
        "queue": "⏳ Navbatda…", "checking": "🔎 Havola tekshirilmoqda…", "download": "⬇️ Yuklanmoqda…",
        "retry": "🔁 Boshqa usulni sinayapman…", "upload": "📤 Yuborilmoqda…",
        "too_long": "⛔ Video {m} daqiqadan uzun. MP3 ni sinab ko'ring.",
        "too_big": "⛔ Eng past sifatda ham 50 MB ga sig'maydi. MP3 ni sinab ko'ring.",
        "live": "⛔ Jonli efirlar qo'llab-quvvatlanmaydi.",
        "private": "🔒 Video mavjud emas: yopiq yoki o'chirilgan.",
        "no_video": "📷 Bu postda video yo'q, faqat rasm. Reels yoki videoli post havolasini yuboring.",
        "age": "🔞 Videoda yosh cheklovi bor: YouTube uni faqat 18+ akkauntlarga beradi. Yuklab bo'lmaydi.",
        "geo": "🌍 Video bot serveri joylashgan mamlakat uchun yopiq. Yuklab bo'lmaydi.",
        "login": "🔐 {svc} videoni akkauntga kirmasdan bermadi. Odatda vaqtinchalik: 10–15 daqiqadan so'ng urinib ko'ring.",
        "blocked": "🚧 Xizmat serverdan yuklashni bloklamoqda. Bir necha daqiqadan so'ng urinib ko'ring.",
        "timeout": "⏱ Ajratilgan vaqtda ulgurmadim. MP3 yoki qisqaroq videoni sinab ko'ring.",
        "fail": "❌ Yuklab bo'lmadi. Havolani tekshirib, qayta urinib ko'ring.",
        "fallback_mp3": "📦 Video Telegram botlar limitiga (50 MB) sig'maydi, ovozni MP3 da yuboraman.",
        "photo_only_mp3": "🖼 Bu postda ovoz yo'q, faqat rasm. Rasmlarni yuboraman.",
        "skipped": "⚠️ Ba'zi fayllar 50 MB dan katta, Telegram botlarga ularni yuborishga ruxsat bermaydi: {n} ta.",
        "credit": "@linkster_bot yordamida yuklab olindi",
    },
}


def lang_of(user: dict) -> str:
    return "uz" if (user.get("language_code") or "").startswith("uz") else "ru"


def clean_url(text):
    m = URL_RE.search(text or "")
    if not m:
        return None, "no_url"
    url = m.group(0).rstrip(".,);]»")
    host = (urlparse(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    kind = ALLOWED.get(host)
    return (url, kind) if kind else (None, "bad_host")


def classify_error(err: str) -> str:
    e = err.lower()
    if "there is no video in this post" in e:
        return "no_video"
    if any(s in e for s in ("age-restricted", "age restricted", "confirm your age", "inappropriate for some users")):
        return "age"
    if any(s in e for s in ("not available in your country", "geo restrict", "geo-restrict", "blocked it in your country",
                            "not made this video available in your country")):
        return "geo"
    if any(s in e for s in ("private video", "this account is private", "has been removed", "video unavailable")):
        return "private"
    if "no video formats found" in e:
        return "login"
    if any(s in e for s in ("login required", "log in", "sign in", "cookies", "rate-limit", "rate limit",
                            "empty media response", "confirm you")):
        return "login"
    if any(s in e for s in ("private", "unavailable", "removed", "not available", "geo", "country",
                            "members-only", "does not exist", "no video", "age")):
        return "private"
    if any(s in e for s in ("403", "429", "too many requests", "bot")):
        return "blocked"
    return "fail"


# ---------- Telegram ----------
def tg(method, **data):
    try:
        r = requests.post(f"{API}/{method}", json=data, timeout=20)
        return r.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}


def tg_upload(method, field, path: Path, timeout=200, **data):
    """Upload a file. A 5xx or a timeout does NOT mean failure: Telegram often finishes
    processing a big file after its gateway gave up, so such results are marked uncertain."""
    try:
        with open(path, "rb") as f:
            r = requests.post(f"{API}/{method}", data=data, files={field: (path.name, f)}, timeout=timeout)
        try:
            j = r.json()
        except ValueError:
            j = {"ok": False, "error_code": r.status_code, "description": r.text[:200]}
    except requests.RequestException as e:
        return {"ok": False, "uncertain": True, "description": repr(e)[:200]}
    if not j.get("ok") and (j.get("error_code") or 0) >= 500:
        j["uncertain"] = True
    return j


def send_media(chat_id, files, caption, timeout):
    """files: [(Path, 'photo'|'video')]. One file -> sendPhoto/sendVideo; more -> albums of 10.
    Returns the last Telegram result; 'uncertain' results count as delivered."""
    last = {"ok": True}
    if len(files) == 1:
        p, t = files[0]
        if t == "photo":
            last = tg_upload("sendPhoto", "photo", p, timeout=timeout, chat_id=chat_id, caption=caption)
            if not last.get("ok") and not last.get("uncertain"):
                last = tg_upload("sendDocument", "document", p, timeout=timeout, chat_id=chat_id, caption=caption)
        else:
            last = tg_upload("sendVideo", "video", p, timeout=timeout, chat_id=chat_id, caption=caption, supports_streaming="true")
            if not last.get("ok") and not last.get("uncertain"):
                last = tg_upload("sendDocument", "document", p, timeout=timeout, chat_id=chat_id, caption=caption)
        return last
    for start in range(0, len(files), 10):
        chunk = files[start:start + 10]
        if len(chunk) == 1:   # Telegram albums need 2+ items
            last = send_media(chat_id, chunk, caption if start == 0 else "", timeout)
            continue
        media, handles = [], {}
        try:
            for i, (p, t) in enumerate(chunk):
                m = {"type": t, "media": f"attach://f{i}"}
                if t == "video":
                    m["supports_streaming"] = True
                if i == 0 and start == 0 and caption:
                    m["caption"] = caption
                media.append(m)
                handles[f"f{i}"] = (p.name, open(p, "rb"))
            try:
                r = requests.post(f"{API}/sendMediaGroup", data={"chat_id": chat_id, "media": json.dumps(media)},
                                  files=handles, timeout=timeout)
                last = r.json() if r.text.lstrip().startswith("{") else {"ok": False, "error_code": r.status_code}
            except requests.RequestException as e:
                last = {"ok": False, "uncertain": True, "description": repr(e)[:200]}
            if not last.get("ok") and (last.get("error_code") or 0) >= 500:
                last["uncertain"] = True
        finally:
            for _, (_, f) in handles.items():
                f.close()
        if not last.get("ok") and not last.get("uncertain"):
            return last
    return last


def to_mp3(src: Path, out: Path, kbps):
    r = subprocess.run([str(TMP / "ffmpeg"), "-y", "-i", str(src), "-vn", "-codec:a", "libmp3lame",
                        "-b:a", f"{kbps}k", str(out)], capture_output=True, timeout=200)
    if r.returncode != 0 or not out.exists():
        raise JobError("fail", detail=f"ffmpeg: {r.stderr[-300:].decode(errors='ignore')}")
    return out


def kick_worker(payload: dict):
    """Fire-and-forget POST to /api/worker (must outlive this request)."""
    host = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") or os.environ["VERCEL_URL"]
    body = json.dumps({**payload, "secret": SECRET})
    c = http.client.HTTPSConnection(host, timeout=8)
    c.request("POST", "/api/worker", body, {"Content-Type": "application/json"})
    try:
        c.sock.settimeout(1.5)
        c.getresponse()
    except Exception:
        pass
    finally:
        try:
            c.close()
        except Exception:
            pass


def who(user):
    """Public Telegram profile fields to store next to the numeric ID."""
    user = user or {}
    return {k: user.get(k) for k in ("first_name", "last_name", "username") if user.get(k)}


def log(kind, user_id=None, **kw):
    """Fire metrics event to Supabase. Never raises, never blocks long."""
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not (url and key and os.environ.get("LOG_KEY")):
        return
    try:
        requests.post(f"{url}/rest/v1/rpc/linkster_log", timeout=3,
                      headers={"apikey": key, "Content-Type": "application/json"},
                      json={"p_key": os.environ["LOG_KEY"], "p": {"kind": kind, "user_id": user_id, **kw}})
    except Exception as e:
        print("log failed", repr(e))


def verify_init_data(init_data: str, max_age=86400):
    """Validate Telegram WebApp initData. Returns user dict or None."""
    import hmac
    from urllib.parse import parse_qsl
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        got = pairs.pop("hash", "")
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got):
            return None
        if time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        return json.loads(pairs["user"])
    except Exception:
        return None


# ---------- tools ----------
def _exe(src: Path, name: str) -> str:
    dst = TMP / name
    if not dst.exists():
        shutil.copy(src, dst)
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(dst)


def tools():
    import imageio_ffmpeg
    ff = _exe(Path(imageio_ffmpeg.get_ffmpeg_exe()), "ffmpeg")
    qjs = _exe(HERE / "bin" / "qjs", "qjs")
    return ff, qjs


def cookies_file():
    if os.environ.get("COOKIES_B64"):
        p = TMP / "cookies.txt"
        p.write_bytes(base64.b64decode(os.environ["COOKIES_B64"]))
        return str(p)
    return None


CLIENT_LADDER = [None, ["tv"], ["web_safari"], ["mweb"], ["android_vr"], ["ios"], ["web_embedded"]]


def ydl_opts(outdir: Path, client=None, extra=None):
    ff, qjs = tools()
    o = {"outtmpl": str(outdir / "%(id)s.%(ext)s"), "noplaylist": True, "quiet": True, "no_warnings": True, "noprogress": True,
         "restrictfilenames": True, "retries": 3, "fragment_retries": 3, "socket_timeout": 25,
         "concurrent_fragment_downloads": 6, "ffmpeg_location": str(TMP),
         "js_runtimes": {"quickjs": {"path": qjs}}, "max_filesize": 400 * 1024 * 1024}
    if client:
        o["extractor_args"] = {"youtube": {"player_client": client}}
    if os.environ.get("PROXY_URL"):
        o["proxy"] = os.environ["PROXY_URL"]
    ck = cookies_file()
    if ck:
        o["cookiefile"] = ck
    o.update(extra or {})
    return o


class JobError(Exception):
    def __init__(self, key, detail=None, **kw):
        self.key, self.kw, self.detail = key, kw, detail


def trace(*a):
    """Diagnostics to stderr, flushed, so they reach the Vercel runtime logs."""
    print(*a, file=sys.stderr, flush=True)


def with_ladder(fn, kind, t0, notify):
    """Run fn(client) across client variants; first success wins. Returns (result, last_error_key)."""
    ladder = CLIENT_LADDER if kind == "yt" else [None]
    last, errs = None, []
    for i, c in enumerate(ladder):
        if time.time() - t0 > DEADLINE - 40:
            raise JobError("timeout", detail=" | ".join(errs) or None)
        try:
            return fn(c)
        except JobError:
            raise
        except Exception as e:
            last = classify_error(str(e))
            errs.append(f"{c or 'default'}: {str(e)[:220]}")
            trace(f'[ladder] client={c} err={str(e)[:300]}')
            if "live" in str(e).lower() and "is live" in str(e).lower():
                raise JobError("live", detail=errs[-1])
            if last in ("no_video", "age", "geo"):   # no other client will change this
                raise JobError(last, detail=" | ".join(errs))
            if last == "private" and i >= 1:  # confirmed by 2 clients
                raise JobError("private", detail=" | ".join(errs))
            if i == 0:
                notify("retry")
    raise JobError(last or "fail", detail=" | ".join(errs))


def probe(url, outdir, client):
    import yt_dlp
    with yt_dlp.YoutubeDL({**ydl_opts(outdir, client), "skip_download": True}) as y:
        info = y.extract_info(url, download=False)
    if info.get("_type") == "playlist" and info.get("entries"):
        info = next(e for e in info["entries"] if e)
    return info


def pick_height(info, cap=MAX_BYTES):
    dur = info.get("duration") or 0
    fm = info.get("formats") or []
    ab = max([f.get("abr") or f.get("tbr") or 0 for f in fm if f.get("vcodec") == "none"] or [128])
    for h in (1080, 720, 480, 360, 240, 144):
        vs = [f for f in fm if f.get("vcodec") not in (None, "none") and (f.get("height") or 0) <= h]
        if not vs:
            continue
        v = max(vs, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
        size = v.get("filesize") or v.get("filesize_approx")
        if not size and v.get("tbr") and dur:
            size = (v["tbr"] + ab) * 1000 / 8 * dur
        elif size and v.get("acodec") in (None, "none"):
            size += ab * 1000 / 8 * dur
        if size is None or size <= cap * 0.95:
            return h
    return 720 if not fm or not any(f.get('height') for f in fm) else 144


def download_video(url, outdir, client, height):
    import yt_dlp
    fmt = (f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/bv*[height<={height}]+ba/"
           f"b[height<={height}][ext=mp4]/b[height<={height}]/b")
    o = ydl_opts(outdir, client, {"format": fmt, "merge_output_format": "mp4"})
    with yt_dlp.YoutubeDL(o) as y:
        y.extract_info(url, download=True)
    files = [f for f in outdir.iterdir() if f.suffix in (".mp4", ".mkv", ".webm")]
    if not files:
        raise JobError("fail")
    return max(files, key=lambda f: f.stat().st_size)


def download_audio(url, outdir, client, kbps):
    import yt_dlp
    o = ydl_opts(outdir, client, {"format": "bestaudio/best"})
    with yt_dlp.YoutubeDL(o) as y:
        y.extract_info(url, download=True)
    src = max(outdir.iterdir(), key=lambda f: f.stat().st_size)
    return to_mp3(src, outdir / "audio.mp3", kbps)


def run_job(chat_id, msg_id, url, fmt, lang, source="bot"):
    t0 = time.time()
    tx = T[lang]
    kind = clean_url(url)[1]

    def status(key, **kw):
        kw = {"svc": "Instagram" if kind == "ig" else "YouTube", **kw}
        tg("editMessageText", chat_id=chat_id, message_id=msg_id, text=tx[key].format(**kw))

    def ok_log(nbytes, detail=None):
        log("job_ok", chat_id, lang=lang, platform=kind, fmt=fmt, source=source,
            ms=int((time.time() - t0) * 1000), bytes=nbytes, detail=detail)

    def fail_log(err, detail=None):
        trace(f"[job] fail err={err} url={url} detail={(detail or '')[:600]}")
        log("job_fail", chat_id, lang=lang, platform=kind, fmt=fmt, source=source,
            ms=int((time.time() - t0) * 1000), err=err, detail=detail)

    def finish(r, nbytes, note=None):
        if r.get("uncertain"):
            note = f"upload uncertain, assumed delivered: {r.get('description', '')}"[:300]
        elif not r.get("ok"):
            raise JobError("fail", detail=f"telegram upload: {str(r)[:300]}")
        tg("deleteMessage", chat_id=chat_id, message_id=msg_id)
        ok_log(nbytes, detail=note)

    def ladder(fn):
        """with_ladder plus one more pass after a pause when the service shows a login/bot wall."""
        try:
            return with_ladder(fn, kind, t0, lambda k: status("retry"))
        except JobError as e:
            if e.key in ("login", "blocked") and time.time() - t0 < 110:
                status("retry")
                time.sleep(6)
                return with_ladder(fn, kind, t0, lambda k: None)
            raise

    def ig_direct():
        """Instagram posts via ig.py: photos, carousels and videos. Returns True when handled."""
        import ig
        try:
            res = ig.fetch(url, cookies_file(), ydl_opts(work))
        except ig.IGError as e:
            ig_errs.append(e.detail)
            return False
        items = res["items"]
        cap = f"{(res.get('caption') or '').strip()[:300]}\n\n{tx['credit']}".strip()
        vids = [i for i in items if i["type"] == "video"]
        if fmt == "mp3" and vids:
            status("download")
            src = work / "ig_src.mp4"
            ig.download(vids[0], src, 300 * 1024 * 1024)
            out = to_mp3(src, work / "audio.mp3", 192)
            status("upload")
            left = max(30, DEADLINE + 25 - (time.time() - t0))
            r = tg_upload("sendAudio", "audio", out, timeout=left, chat_id=chat_id, caption=cap,
                          title=(res.get("owner") or "Instagram")[:64])
            finish(r, out.stat().st_size, "ig direct")
            return True
        if fmt == "mp3":
            tg("sendMessage", chat_id=chat_id, text=tx["photo_only_mp3"])
        status("download")
        files, skipped, total = [], 0, 0
        for n, it in enumerate(items):
            ext = "mp4" if it["type"] == "video" else "jpg"
            p = work / f"ig_{n:02d}.{ext}"
            try:
                total += ig.download(it, p, MAX_BYTES if it["type"] == "video" else 10 * 1024 * 1024)
                files.append((p, it["type"]))
            except ig.IGError:
                skipped += 1
        if not files:
            ig_errs.append(f"all {len(items)} items over the size limit")
            return False
        if skipped:
            tg("sendMessage", chat_id=chat_id, text=tx["skipped"].format(n=skipped))
        status("upload")
        left = max(30, DEADLINE + 25 - (time.time() - t0))
        r = send_media(chat_id, files, cap, left)
        finish(r, total, f"ig direct: {len(files)} item(s)")
        return True

    ig_errs = []
    work = Path(tempfile.mkdtemp(dir=TMP))
    try:
        tools()
        status("checking")
        if kind == "ig" and ig_direct():
            return
        try:
            info = ladder(lambda c: probe(url, work, c))
        except JobError as e:
            if ig_errs:
                e.detail = f"{e.detail} || ig direct: {' | '.join(ig_errs)}"
            raise
        if info.get("is_live"):
            raise JobError("live")
        dur = int(info.get("duration") or 0)
        title = (info.get("title") or "video")[:100]
        note = None
        if dur > MAX_DURATION and fmt == "mp4":
            # too long for any video quality under 50 MB: send the sound instead of an error
            tg("sendMessage", chat_id=chat_id, text=tx["fallback_mp3"])
            fmt, note = "mp3", "fallback to mp3: too long"
        status("download")
        if fmt == "mp3":
            kbps = 192 if dur <= 1800 else 128 if dur <= 3000 else 96
            if dur and kbps * 1000 / 8 * dur > MAX_BYTES:
                kbps = 64
            path = ladder(lambda c: download_audio(url, work, c, kbps))
            if path.stat().st_size > MAX_BYTES:
                path = to_mp3(path, work / "audio_small.mp3", 48)
                if path.stat().st_size > MAX_BYTES:
                    raise JobError("too_big")
        else:
            h = pick_height(info)
            while True:
                path = ladder(lambda c: download_video(url, work, c, h))
                if path.stat().st_size <= MAX_BYTES:
                    break
                lower = [x for x in (720, 480, 360, 240, 144) if x < h]
                if not lower:
                    # even 144p is over 50 MB: the sound still fits, send it instead of an error
                    tg("sendMessage", chat_id=chat_id, text=tx["fallback_mp3"])
                    fmt, note = "mp3", "fallback to mp3: too big"
                    kbps = 96 if dur <= 3600 else 64
                    path = to_mp3(path, work / "audio.mp3", kbps)
                    if path.stat().st_size > MAX_BYTES:
                        raise JobError("too_big")
                    break
                for f in work.iterdir():
                    if f.suffix in (".mp4", ".mkv", ".webm"):
                        f.unlink()
                h = lower[0]
        status("upload")
        cap = f"{title[:200]}\n\n{tx['credit']}"
        left = max(30, DEADLINE + 25 - (time.time() - t0))   # never outlive the function
        if fmt == "mp3":
            r = tg_upload("sendAudio", "audio", path, timeout=left, chat_id=chat_id, title=title, caption=cap,
                          performer=(info.get("uploader") or "")[:64], duration=dur)
        else:
            r = tg_upload("sendVideo", "video", path, timeout=left, chat_id=chat_id, caption=cap, supports_streaming="true",
                          duration=dur, width=info.get("width") or "", height=info.get("height") or "")
            if not r.get("ok") and not r.get("uncertain"):   # a real rejection: retry as a plain file
                left = max(30, DEADLINE + 25 - (time.time() - t0))
                r = tg_upload("sendDocument", "document", path, timeout=left, chat_id=chat_id, caption=cap)
        # Telegram's gateway may time out while the file still arrives: finish() treats that as delivered.
        finish(r, path.stat().st_size, note)
    except JobError as e:
        status(e.key, **e.kw)
        fail_log(e.key, e.detail)
    except Exception as e:  # noqa
        k = classify_error(str(e))
        status(k)
        fail_log(k, f"unexpected: {repr(e)[:500]}")
    finally:
        shutil.rmtree(work, ignore_errors=True)  # nothing is kept on our side
