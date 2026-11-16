import json, os, sys, tempfile
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import core


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        if q.get("s", [""])[0] != core.SECRET:
            self.send_response(403); self.end_headers(); return
        url = q.get("u", [""])[0]
        out = {}
        core.tools()
        from pathlib import Path
        for c in core.CLIENT_LADDER:
            try:
                info = core.probe(url, Path(tempfile.mkdtemp(dir=core.TMP)), c)
                out[str(c)] = f"OK {info.get('title')} formats={len(info.get('formats') or [])}"
            except Exception as e:
                out[str(c)] = "ERR " + str(e)[:300]
        b = json.dumps(out, ensure_ascii=False, indent=1).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.end_headers(); self.wfile.write(b)
