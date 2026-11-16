"""Admin metrics proxy: ?key=ADMIN_KEY&days=14 -> JSON from Supabase RPC.

Users seen before names were logged come back in `unnamed`; their public Telegram
profile (first name, @username) is looked up with getChat and saved, so the
dashboard shows names instead of numeric IDs.
"""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import requests

SB = lambda: os.environ["SUPABASE_URL"]
HDR = lambda: {"apikey": os.environ["SUPABASE_KEY"], "Content-Type": "application/json"}


def lookup(uid):
    """getChat -> {user_id, first_name, last_name, username} or None. Never raises."""
    try:
        r = requests.get(f"https://api.telegram.org/bot{os.environ['BOT_TOKEN']}/getChat",
                         params={"chat_id": uid}, timeout=4).json()
        c = r.get("result") or {}
        if not r.get("ok") or not (c.get("first_name") or c.get("username")):
            return None
        u = {"user_id": uid, **{k: c.get(k) for k in ("first_name", "last_name", "username") if c.get(k)}}
        if os.environ.get("LOG_KEY"):
            requests.post(f"{SB()}/rest/v1/rpc/linkster_set_user", timeout=4, headers=HDR(),
                          json={"p_key": os.environ["LOG_KEY"], "p": u})
        return u
    except Exception as e:
        print("lookup failed", uid, repr(e))
        return None


def fill_names(data):
    ids = [i for i in (data.pop("unnamed", None) or []) if i]
    if not ids or not os.environ.get("BOT_TOKEN"):
        return
    with ThreadPoolExecutor(8) as ex:
        found = {u["user_id"]: u for u in ex.map(lookup, ids) if u}
    for row in (data.get("top_users") or []) + (data.get("recent") or []):
        u = found.get(row.get("user_id"))
        if u and not (row.get("first_name") or row.get("username")):
            row.update({k: v for k, v in u.items() if k != "user_id"})


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
            r = requests.post(f"{SB()}/rest/v1/rpc/linkster_stats", timeout=15, headers=HDR(),
                              json={"p_key": key, "p_days": days})
        except Exception:
            return self._send(502, b'{"error":"upstream"}')
        if r.status_code != 200:
            return self._send(403, b'{"error":"denied"}')
        data = r.json()
        fill_names(data)
        self._send(200, json.dumps(data, ensure_ascii=False).encode())
