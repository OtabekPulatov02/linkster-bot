import json, os, sys
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import core
from core import T, tg, clean_url, lang_of


def handle(u):
    if "callback_query" in u:
        cq = u["callback_query"]
        msg = cq.get("message") or {}
        lang = lang_of(cq["from"])
        data = cq.get("data", "")
        if not data.startswith("d:") or not msg:
            return tg("answerCallbackQuery", callback_query_id=cq["id"])
        fmt = "mp3" if data == "d:mp3" else "mp4"
        src = (msg.get("reply_to_message") or {}).get("text") or ""
        url, kind = clean_url(src)
        if not url:
            tg("answerCallbackQuery", callback_query_id=cq["id"], text=T[lang]["expired"], show_alert=True)
            return
        tg("answerCallbackQuery", callback_query_id=cq["id"])
        tg("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"], text=T[lang]["queue"])
        core.log("link", msg["chat"]["id"], lang=lang, platform=kind, fmt=fmt, source="bot", **core.who(cq.get("from")))
        core.kick_worker({"chat_id": msg["chat"]["id"], "msg_id": msg["message_id"], "url": url, "fmt": fmt, "lang": lang})
        return
    m = u.get("message") or {}
    if not m or "from" not in m:
        return
    lang, chat = lang_of(m["from"]), m["chat"]["id"]
    text = m.get("text") or m.get("caption") or ""
    if text.startswith(("/start", "/help")):
        core.log("start", m["from"]["id"], lang=lang, source="bot", **core.who(m["from"]))
        tg("sendMessage", chat_id=chat, text=T[lang]["start"], parse_mode="HTML")
        return
    url, kind = clean_url(text)
    if not url:
        tg("sendMessage", chat_id=chat, text=T[lang][kind], reply_to_message_id=m["message_id"])
        return
    kb = {"inline_keyboard": [[{"text": T[lang]["mp4"], "callback_data": "d:mp4"},
                               {"text": T[lang]["mp3"], "callback_data": "d:mp3"}]]}
    tg("sendMessage", chat_id=chat, text=T[lang]["choose"], reply_to_message_id=m["message_id"], reply_markup=kb)


class handler(BaseHTTPRequestHandler):
    def _ok(self, body=b"ok"):
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        self._ok()

    def do_POST(self):
        if self.headers.get("X-Telegram-Bot-Api-Secret-Token") != core.SECRET:
            self.send_response(403); self.end_headers(); return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            handle(json.loads(self.rfile.read(n) or b"{}"))
        except Exception as e:
            print("webhook error", repr(e))
        self._ok()
