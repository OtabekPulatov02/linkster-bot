---
title: Linkster Bot
emoji: 🎬
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# Linkster bot

Telegram bot: send a YouTube or Instagram link, get an MP4 or MP3 back.

- Stack: Python 3.12, aiogram 3, yt-dlp, ffmpeg (Docker).
- Env: `BOT_TOKEN` (required), `COOKIES_B64` (optional, base64 Netscape cookies for Instagram/YouTube),
  `PROXY_URL`, `MAX_UPLOAD_MB` (49), `MAX_DURATION_MIN` (90), `MAX_PARALLEL_JOBS` (2), `ADMIN_ID`.
- Telegram cloud limit is 50 MB; video quality drops automatically until the file fits.
- Run: `docker build -t linkster . && docker run -e BOT_TOKEN=... linkster`
- Tests: `python test_bot.py`
