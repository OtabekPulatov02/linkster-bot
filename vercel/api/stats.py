"""Admin metrics proxy: ?key=ADMIN_KEY&days=14 -> JSON from Supabase RPC."""
import json, os, sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import requests


class handler(BaseHTTPRequestHandler):
    def _send(self, code, b):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        key = self.headers.get("X-Admin-Key") or (q.get("key") or [""])[0]
        days = int((q.get("days") or ["14"])[0] or 14)
        try:
            r = requests.post(f"{os.environ['SUPABASE_URL']}/rest/v1/rpc/linkster_stats", timeout=15,
                              headers={"apikey": os.environ["SUPABASE_KEY"], "Content-Type": "application/json"},
                              json={"p_key": key, "p_days": days})
        except Exception:
            return self._send(502, b'{"error":"upstream"}')
        if r.status_code != 200:
            return self._send(403, b'{"error":"denied"}')
        self._send(200, r.content)
