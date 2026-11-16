"""Mini App backend: validates Telegram initData, queues a download into the user's chat."""
import json, os, sys
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import core
from core import T, tg, clean_url, lang_of


class handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json(400, {"error": "bad_json"})
        user = core.verify_init_data(body.get("initData", ""))
        if not user:
            return self._json(401, {"error": "auth"})
        lang = lang_of(user)
        uid = user["id"]
        action = body.get("action")
        if action == "open":
            core.log("open", uid, lang=lang, source="miniapp")
            return self._json(200, {"ok": True, "lang": lang})
        if action == "download":
            url, kind = clean_url(body.get("url", ""))
            fmt = "mp3" if body.get("fmt") == "mp3" else "mp4"
            if not url:
                return self._json(400, {"error": kind})
            r = tg("sendMessage", chat_id=uid, text=T[lang]["queue"])
            if not r.get("ok"):
                return self._json(409, {"error": "no_chat"})  # user has not started the bot
            core.log("link", uid, lang=lang, platform=kind, fmt=fmt, source="miniapp")
            core.kick_worker({"chat_id": uid, "msg_id": r["result"]["message_id"], "url": url,
                              "fmt": fmt, "lang": lang, "source": "miniapp"})
            return self._json(200, {"ok": True, "platform": kind})
        return self._json(400, {"error": "action"})

    def do_GET(self):
        self._json(200, {"ok": True})
