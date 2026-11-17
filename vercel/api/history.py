"""Admin: every download ever, newest first, with keyset paging.
GET /api/history?limit=50&before=<ISO ts>&status=ok|fail&platform=yt|ig&q=<name, @username or ID>
Header X-Admin-Key (or ?key=). The admin key is checked inside the database function."""
import json, os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import requests


class handler(BaseHTTPRequestHandler):
    def _send(self, code, b):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        g = lambda k: (q.get(k) or [""])[0].strip() or None
        key = self.headers.get("X-Admin-Key") or g("key") or ""
        try:
            limit = int(g("limit") or 50)
        except ValueError:
            limit = 50
        body = {"p_key": key, "p_limit": limit, "p_before": g("before"),
                "p_status": g("status") if g("status") in ("ok", "fail") else None,
                "p_platform": g("platform") if g("platform") in ("yt", "ig") else None,
                "p_q": (g("q") or "")[:80] or None}
        try:
            r = requests.post(f"{os.environ['SUPABASE_URL']}/rest/v1/rpc/linkster_history", timeout=15,
                              headers={"apikey": os.environ["SUPABASE_KEY"], "Content-Type": "application/json"},
                              json=body)
        except Exception:
            return self._send(502, b'{"error":"upstream"}')
        if r.status_code != 200:
            return self._send(403 if "denied" in r.text else 502, b'{"error":"denied"}' if "denied" in r.text else b'{"error":"upstream"}')
        self._send(200, json.dumps(r.json(), ensure_ascii=False).encode())
