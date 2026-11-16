#!/bin/sh
# YouTube/Instagram change often: refresh yt-dlp on every start (falls back to the baked-in version).
pip install --user -q -U "yt-dlp[default]" 2>/dev/null || echo "yt-dlp update skipped"
export PATH="$HOME/.local/bin:$PATH"
exec python bot.py
