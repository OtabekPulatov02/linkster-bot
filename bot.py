"""Linkster bot: YouTube / Instagram link -> MP4 or MP3 in Telegram."""
import asyncio
import base64
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

TOKEN = os.environ["BOT_TOKEN"]
MAX_BYTES = int(os.getenv("MAX_UPLOAD_MB", "49")) * 1024 * 1024  # Telegram cloud API: 50 MB
MAX_DURATION = int(os.getenv("MAX_DURATION_MIN", "90")) * 60
GLOBAL_JOBS = int(os.getenv("MAX_PARALLEL_JOBS", "2"))
COOLDOWN = float(os.getenv("USER_COOLDOWN_SEC", "3"))
PROXY = os.getenv("PROXY_URL") or None
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
WORKDIR = Path(os.getenv("WORKDIR", tempfile.gettempdir())) / "linkster"
WORKDIR.mkdir(parents=True, exist_ok=True)

COOKIES = None
if os.getenv("COOKIES_B64"):  # base64 of a Netscape cookies.txt (YouTube and/or Instagram)
    COOKIES = WORKDIR / "cookies.txt"
    COOKIES.write_bytes(base64.b64decode(os.environ["COOKIES_B64"]))
elif os.getenv("COOKIES_FILE") and Path(os.environ["COOKIES_FILE"]).exists():
    COOKIES = Path(os.environ["COOKIES_FILE"])

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
ALLOWED = {
    "youtube.com": "yt", "m.youtube.com": "yt", "music.youtube.com": "yt", "youtu.be": "yt",
    "youtube-nocookie.com": "yt", "instagram.com": "ig", "instagr.am": "ig",
}

T = {
    "ru": {
        "start": ("👋 <b>Привет!</b>\n\nПришли ссылку на видео из <b>YouTube</b> или <b>Instagram</b> "
                  "(Reels, посты, Shorts), и я пришлю файл в <b>MP4</b> или <b>MP3</b>.\n\n"
                  "Лимит Telegram для ботов — 50 МБ: длинные видео я автоматически сжимаю по качеству."),
        "help": ("ℹ️ Отправь ссылку, выбери формат — MP4 (видео) или MP3 (звук).\n"
                 "Приватные и закрытые посты не скачиваются. Команда /lang — сменить язык."),
        "choose": "Что скачать?",
        "mp4": "🎬 MP4 (видео)", "mp3": "🎵 MP3 (звук)",
        "no_url": "🔗 Пришли ссылку на YouTube или Instagram.",
        "bad_host": "😕 Поддерживаются только ссылки YouTube и Instagram.",
        "busy": "⏳ Предыдущая загрузка ещё идёт. Подожди, пожалуйста.",
        "expired": "⌛ Ссылка устарела, отправь её ещё раз.",
        "queue": "⏳ В очереди…", "checking": "🔎 Проверяю ссылку…",
        "download": "⬇️ Скачиваю…", "convert": "⚙️ Обрабатываю…", "upload": "📤 Отправляю…",
        "too_long": "⛔ Видео длиннее {m} мин — слишком большое для бота.",
        "too_big": "⛔ Не удалось уложиться в лимит 50 МБ даже в минимальном качестве. Попробуй MP3.",
        "live": "⛔ Прямые эфиры не поддерживаются.",
        "private": "🔒 Видео недоступно: приватное, удалено, с возрастным ограничением или закрыто для региона.",
        "login": "🔐 Instagram/YouTube просят вход для этого видео. Администратор бота может добавить cookies.",
        "blocked": "🚧 Сервис временно блокирует загрузку. Попробуй через несколько минут.",
        "fail": "❌ Не получилось скачать. Проверь ссылку и попробуй ещё раз.",
        "done_mp4": "🎬 Готово", "lang_set": "✅ Язык: русский", "lang_pick": "Выбери язык:",
    },
    "uz": {
        "start": ("👋 <b>Salom!</b>\n\n<b>YouTube</b> yoki <b>Instagram</b> (Reels, post, Shorts) havolasini yuboring — "
                  "men uni <b>MP4</b> yoki <b>MP3</b> qilib yuboraman.\n\n"
                  "Telegram botlar uchun limit — 50 MB: uzun videolar sifati avtomatik pasaytiriladi."),
        "help": ("ℹ️ Havolani yuboring va formatni tanlang — MP4 (video) yoki MP3 (ovoz).\n"
                 "Yopiq va maxfiy postlar yuklanmaydi. /lang — tilni almashtirish."),
        "choose": "Nimani yuklab olay?",
        "mp4": "🎬 MP4 (video)", "mp3": "🎵 MP3 (ovoz)",
        "no_url": "🔗 YouTube yoki Instagram havolasini yuboring.",
        "bad_host": "😕 Faqat YouTube va Instagram havolalari qo'llab-quvvatlanadi.",
        "busy": "⏳ Oldingi yuklash hali tugamadi. Biroz kuting.",
        "expired": "⌛ Havola eskirdi, uni qayta yuboring.",
        "queue": "⏳ Navbatda…", "checking": "🔎 Havola tekshirilmoqda…",
        "download": "⬇️ Yuklanmoqda…", "convert": "⚙️ Qayta ishlanmoqda…", "upload": "📤 Yuborilmoqda…",
        "too_long": "⛔ Video {m} daqiqadan uzun — bot uchun juda katta.",
        "too_big": "⛔ Eng past sifatda ham 50 MB ga sig'maydi. MP3 ni sinab ko'ring.",
        "live": "⛔ Jonli efirlar qo'llab-quvvatlanmaydi.",
        "private": "🔒 Video mavjud emas: yopiq, o'chirilgan, yosh cheklovi yoki hudud bo'yicha yopiq.",
        "login": "🔐 Bu video uchun kirish talab qilinmoqda. Bot administratori cookies qo'shishi mumkin.",
        "blocked": "🚧 Xizmat vaqtincha yuklashni bloklamoqda. Bir necha daqiqadan so'ng urinib ko'ring.",
        "fail": "❌ Yuklab bo'lmadi. Havolani tekshirib, qayta urinib ko'ring.",
        "done_mp4": "🎬 Tayyor", "lang_set": "✅ Til: o'zbekcha", "lang_pick": "Tilni tanlang:",
    },
}
user_lang: dict[int, str] = {}
pending: dict[str, tuple[int, str, float]] = {}  # token -> (user_id, url, created)
active_users: set[int] = set()
last_req: dict[int, float] = {}
sem = asyncio.Semaphore(GLOBAL_JOBS)


def lang_of(user) -> str:
    if user.id in user_lang:
        return user_lang[user.id]
    return "uz" if (user.language_code or "").startswith("uz") else "ru"


def tr(user, key, **kw):
    return T[lang_of(user)][key].format(**kw) if kw else T[lang_of(user)][key]


def clean_url(text: str):
    """Return (url, kind) for the first supported link in text, or (None, reason)."""
    m = URL_RE.search(text or "")
    if not m:
        return None, "no_url"
    url = m.group(0).rstrip(".,);]»")
    host = (urlparse(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    kind = ALLOWED.get(host)
    if not kind:
        return None, "bad_host"
    return url, kind


def classify_error(err: str) -> str:
    e = err.lower()
    if any(s in e for s in ("login required", "log in", "sign in", "cookies", "rate-limit", "rate limit",
                            "empty media response", "confirm you")):
        return "login"
    if any(s in e for s in ("private", "unavailable", "removed", "age", "not available", "geo", "country",
                            "members-only", "does not exist", "no video")):
        return "private"
    if any(s in e for s in ("403", "429", "too many requests", "bot")):
        return "blocked"
    return "fail"


class JobError(Exception):
    def __init__(self, key, **kw):
        self.key, self.kw = key, kw


def base_opts(outdir: Path, hook=None):
    o = {
        "outtmpl": str(outdir / "%(id)s.%(ext)s"),
        "noplaylist": True, "quiet": True, "no_warnings": True, "restrictfilenames": True,
        "retries": 5, "fragment_retries": 5, "socket_timeout": 30, "concurrent_fragment_downloads": 4,
        "js_runtimes": {"node": {}}, "remote_components": ["ejs:github"],
        "max_filesize": 2 * 1024 ** 3,
    }
    if PROXY:
        o["proxy"] = PROXY
    if COOKIES:
        o["cookiefile"] = str(COOKIES)
    if hook:
        o["progress_hooks"] = [hook]
    return o


def probe(url):
    with yt_dlp.YoutubeDL({**base_opts(WORKDIR), "skip_download": True}) as y:
        info = y.extract_info(url, download=False)
    if info.get("_type") == "playlist" and info.get("entries"):
        info = next(e for e in info["entries"] if e)
    return info


def fetch_video(url, outdir: Path, hook, height):
    fmt = (f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/bv*[height<={height}]+ba/"
           f"b[height<={height}][ext=mp4]/b[height<={height}]/b")
    o = {**base_opts(outdir, hook), "format": fmt, "merge_output_format": "mp4",
         "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}]}
    with yt_dlp.YoutubeDL(o) as y:
        y.extract_info(url, download=True)
    files = [f for f in outdir.iterdir() if f.suffix == ".mp4"]
    if not files:
        raise JobError("fail")
    return max(files, key=lambda f: f.stat().st_size)


def fetch_audio(url, outdir: Path, hook, kbps):
    o = {**base_opts(outdir, hook), "format": "bestaudio/best",
         "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": str(kbps)}]}
    with yt_dlp.YoutubeDL(o) as y:
        y.extract_info(url, download=True)
    files = [f for f in outdir.iterdir() if f.suffix == ".mp3"]
    if not files:
        raise JobError("fail")
    return files[0]


def video_meta(path: Path):
    import json
    import subprocess
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height:format=duration", "-of", "json", str(path)],
                             capture_output=True, text=True, timeout=30).stdout
        j = json.loads(out)
        s = j["streams"][0]
        return int(s["width"]), int(s["height"]), int(float(j["format"]["duration"]))
    except Exception:
        return None, None, None


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def safe_edit(msg: Message, text: str, **kw):
    try:
        await msg.edit_text(text, **kw)
    except TelegramBadRequest:
        pass
    except Exception as e:  # network hiccup should not kill the job
        log.warning("edit failed: %s", e)


async def run_job(bot: Bot, cq: CallbackQuery, url: str, fmt: str):
    user = cq.from_user
    status = cq.message
    loop = asyncio.get_running_loop()
    workdir = Path(tempfile.mkdtemp(dir=WORKDIR))
    state = {"last": 0.0, "text": ""}

    def hook(d):
        if d.get("status") != "downloading":
            return
        now = time.monotonic()
        if now - state["last"] < 3:
            return
        state["last"] = now
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        pct = int(d.get("downloaded_bytes", 0) * 100 / total) if total else None
        txt = tr(user, "download") + (f" {min(pct, 99)}%" if pct is not None else "")
        if txt != state["text"]:
            state["text"] = txt
            asyncio.run_coroutine_threadsafe(safe_edit(status, txt), loop)

    try:
        await safe_edit(status, tr(user, "queue"))
        async with sem:
            await safe_edit(status, tr(user, "checking"))
            info = await asyncio.to_thread(probe, url)
            if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
                raise JobError("live")
            dur = info.get("duration") or 0
            if dur and dur > MAX_DURATION:
                raise JobError("too_long", m=MAX_DURATION // 60)
            title = info.get("title") or "video"
            performer = info.get("uploader") or info.get("channel") or ""
            await safe_edit(status, tr(user, "download"))
            await bot.send_chat_action(cq.message.chat.id,
                                       ChatAction.UPLOAD_VIDEO if fmt == "mp4" else ChatAction.UPLOAD_VOICE)
            path = None
            if fmt == "mp3":
                kbps = 192
                if dur:
                    kbps = max(48, min(192, int(MAX_BYTES * 8 / dur / 1000 * 0.95)))
                kbps = next(k for k in (192, 160, 128, 96, 64, 48, 32) if k <= kbps) if kbps >= 32 else 32
                path = await asyncio.to_thread(fetch_audio, url, workdir, hook, kbps)
                if path.stat().st_size > MAX_BYTES:
                    raise JobError("too_big")
            else:
                for h in (1080, 720, 480, 360, 240):
                    for f in workdir.iterdir():
                        f.unlink()
                    path = await asyncio.to_thread(fetch_video, url, workdir, hook, h)
                    if path.stat().st_size <= MAX_BYTES:
                        break
                    path = None
                if path is None:
                    raise JobError("too_big")
            await safe_edit(status, tr(user, "upload"))
            if fmt == "mp4":
                w, h, d = await asyncio.to_thread(video_meta, path)
                await bot.send_video(cq.message.chat.id, FSInputFile(path, filename=f"{path.stem}.mp4"),
                                     caption=esc(title)[:1000], width=w, height=h, duration=d,
                                     supports_streaming=True, request_timeout=600)
            else:
                await bot.send_audio(cq.message.chat.id, FSInputFile(path, filename=f"{path.stem}.mp3"),
                                     title=title[:64], performer=performer[:64] or None,
                                     duration=int(dur) or None, request_timeout=600)
        try:
            await status.delete()
        except Exception:
            pass
    except JobError as e:
        await safe_edit(status, tr(user, e.key, **e.kw))
    except yt_dlp.utils.DownloadError as e:
        log.warning("download error %s: %s", url, e)
        await safe_edit(status, tr(user, classify_error(str(e))))
    except Exception:
        log.exception("job failed %s", url)
        await safe_edit(status, tr(user, "fail"))
    finally:
        active_users.discard(user.id)
        shutil.rmtree(workdir, ignore_errors=True)


dp = Dispatcher()


@dp.message(CommandStart())
async def on_start(m: Message):
    await m.answer(tr(m.from_user, "start"))


@dp.message(Command("help"))
async def on_help(m: Message):
    await m.answer(tr(m.from_user, "help"))


@dp.message(Command("lang"))
async def on_lang(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🇷🇺 Русский", callback_data="l:ru"),
                                                 InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="l:uz")]])
    await m.answer(T["ru"]["lang_pick"] + " / " + T["uz"]["lang_pick"], reply_markup=kb)


@dp.callback_query(F.data.startswith("l:"))
async def on_lang_set(cq: CallbackQuery):
    user_lang[cq.from_user.id] = cq.data[2:] if cq.data[2:] in T else "ru"
    await cq.message.edit_text(tr(cq.from_user, "lang_set"))
    await cq.answer()


@dp.message(F.text)
async def on_text(m: Message):
    if m.text.startswith("/"):
        return
    url, kind = clean_url(m.text)
    if not url:
        return await m.answer(tr(m.from_user, kind))
    now = time.monotonic()
    if now - last_req.get(m.from_user.id, 0) < COOLDOWN:
        return
    last_req[m.from_user.id] = now
    for k in [k for k, v in pending.items() if now - v[2] > 3600]:
        pending.pop(k, None)
    token = uuid.uuid4().hex[:12]
    pending[token] = (m.from_user.id, url, now)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=tr(m.from_user, "mp4"), callback_data=f"d:mp4:{token}"),
        InlineKeyboardButton(text=tr(m.from_user, "mp3"), callback_data=f"d:mp3:{token}")]])
    await m.reply(tr(m.from_user, "choose"), reply_markup=kb)


@dp.callback_query(F.data.startswith("d:"))
async def on_download(cq: CallbackQuery, bot: Bot):
    _, fmt, token = cq.data.split(":")
    item = pending.get(token)
    if not item or item[0] != cq.from_user.id:
        await cq.answer(tr(cq.from_user, "expired"), show_alert=True)
        return
    if cq.from_user.id in active_users:
        await cq.answer(tr(cq.from_user, "busy"), show_alert=True)
        return
    active_users.add(cq.from_user.id)
    pending.pop(token, None)
    await cq.answer()
    asyncio.create_task(run_job(bot, cq, item[1], fmt))


async def main():
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=True)
    me = await bot.get_me()
    log.info("started as @%s (cookies=%s proxy=%s)", me.username, bool(COOKIES), bool(PROXY))
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.run(main())
