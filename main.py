"""
main.py — Local development helper for MLSA Certificate Generator.

Runs a lightweight HTTP server so you can test the full stack locally
without deploying to Vercel.

Usage:
    pip install xhtml2pdf resend
    cp .env.example .env          # fill in your keys
    python main.py

Then open http://localhost:3000 in your browser.

The server serves static files from the project root and routes
POST /api/send to the same handler used by the Vercel function.
"""

import http.server
import importlib.util
import os
import pathlib
from http.server import SimpleHTTPRequestHandler

# ── Load env vars from .env (simple parser, no dotenv dependency) ─────────────

ENV_FILE = pathlib.Path(__file__).parent / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

# ── Import the Vercel handler from api/send.py ────────────────────────────────

_spec = importlib.util.spec_from_file_location(
    "api_send",
    pathlib.Path(__file__).parent / "api" / "send.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ApiHandler = _mod.handler


# ── Combined request handler ──────────────────────────────────────────────────

class DevHandler(SimpleHTTPRequestHandler):
    """
    Routes:
        POST /api/send  →  api/send.py handler
        everything else →  serve as static file from project root
    """

    def do_POST(self):
        if self.path.split("?")[0] == "/api/send":
            self._delegate_to_api()
        else:
            self.send_error(404, "Not found")

    def do_OPTIONS(self):
        if self.path.split("?")[0] == "/api/send":
            self._delegate_to_api(method="OPTIONS")
        else:
            self.send_error(404, "Not found")

    def _delegate_to_api(self, method=None):
        """Instantiate the Vercel-style handler and call do_POST / do_OPTIONS."""
        # Monkey-patch rfile so the handler sees the right body
        api = ApiHandler.__new__(ApiHandler)
        api.rfile   = self.rfile
        api.wfile   = self.wfile
        api.headers = self.headers
        api.path    = self.path

        # Provide send_response / send_header / end_headers / log_message
        api.send_response  = self.send_response
        api.send_header    = self.send_header
        api.end_headers    = self.end_headers
        api.log_message    = lambda *a: None

        if method == "OPTIONS":
            api.do_OPTIONS()
        else:
            api.do_POST()

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")


# ── Main ──────────────────────────────────────────────────────────────────────

PORT = int(os.environ.get("PORT", 3000))

if __name__ == "__main__":
    os.chdir(pathlib.Path(__file__).parent)   # serve files from project root

    with http.server.ThreadingHTTPServer(("", PORT), DevHandler) as srv:
        print(f"\n  MLSA Certificate Generator — dev server")
        print(f"  http://localhost:{PORT}\n")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n  Server stopped.")
