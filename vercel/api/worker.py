import json, os, sys
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import core


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        p = json.loads(self.rfile.read(n) or b"{}")
        if p.get("secret") != core.SECRET:
            self.send_response(403); self.end_headers(); return
        try:
            core.run_job(p["chat_id"], p["msg_id"], p["url"], p["fmt"], p["lang"])
        except Exception as e:
            print("worker error", repr(e))
        self.send_response(200); self.end_headers(); self.wfile.write(b"done")
