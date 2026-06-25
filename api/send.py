"""
MLSA Certificate Generator — Serverless API
POST /api/send

Accepts a list of recipients, renders an HTML certificate for each one,
converts it to PDF with WeasyPrint, then emails it via Resend.

Environment variables (set in Vercel dashboard or .env):
    RESEND_API_KEY   — Resend API key (required)
    EMAIL_FROM       — Verified sender address, e.g. "Certs <certs@yourdomain.com>"
"""

from __future__ import annotations

import base64
import json
import os
import re
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR  = Path(__file__).parent.parent
CERT_DIR  = BASE_DIR / "Templates" / "Certificate"
EMAIL_DIR = BASE_DIR / "Templates" / "Email"

# ── Template rendering ────────────────────────────────────────────────────────

def _inline_css(html: str, css: str, href: str) -> str:
    """Replace a <link rel=stylesheet> tag with an inline <style> block."""
    pattern = re.compile(
        r"<link[^>]+href=[\"']" + re.escape(href) + r"[\"'][^>]*/?>",
        re.IGNORECASE,
    )
    return pattern.sub(f"<style>\n{css}\n</style>", html)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


def render_certificate(name: str, event: str, host: str) -> str:
    html = (CERT_DIR / "index.html").read_text(encoding="utf-8")
    css  = (CERT_DIR / "certificate.css").read_text(encoding="utf-8")

    html = _inline_css(html, css, "certificate.css")
    html = html.replace("{NAME}",  _escape_html(name))
    html = html.replace("{EVENT}", _escape_html(event))
    html = html.replace("{HOST}",  _escape_html(host))
    return html


def render_email(name: str, event: str) -> str:
    html = (EMAIL_DIR / "index.html").read_text(encoding="utf-8")
    css  = (EMAIL_DIR / "email.css").read_text(encoding="utf-8")

    html = _inline_css(html, css, "email.css")
    html = html.replace("{NAME}",  _escape_html(name))
    html = html.replace("{EVENT}", _escape_html(event))
    return html

# ── PDF generation ────────────────────────────────────────────────────────────

def html_to_pdf(html: str) -> bytes:
    try:
        import weasyprint  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "WeasyPrint is not installed. Run: pip install weasyprint"
        ) from exc

    # base_url lets WeasyPrint resolve relative assets (background.png, fonts)
    return weasyprint.HTML(
        string=html,
        base_url=str(CERT_DIR),
    ).write_pdf()

# ── Email sending ─────────────────────────────────────────────────────────────

def send_email(
    to_email: str,
    to_name: str,
    event: str,
    pdf_bytes: bytes,
    email_html: str,
) -> None:
    try:
        import resend  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "resend is not installed. Run: pip install resend"
        ) from exc

    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "RESEND_API_KEY environment variable is not set. "
            "Add it in the Vercel dashboard under Settings → Environment Variables."
        )

    from_addr = os.environ.get(
        "EMAIL_FROM",
        "MLSA Certificates <certificates@yourdomain.com>",
    )

    resend.api_key = api_key

    # Sanitise filename: keep letters, digits, spaces, hyphens
    safe_name = re.sub(r"[^\w\s-]", "", to_name).strip().replace(" ", "_")
    filename  = f"Certificate_{safe_name}.pdf"

    resend.Emails.send({
        "from":    from_addr,
        "to":      [to_email],
        "subject": f"Your Certificate of Participation – {event}",
        "html":    email_html,
        "attachments": [
            {
                "filename": filename,
                "content":  base64.b64encode(pdf_bytes).decode("utf-8"),
            }
        ],
    })

# ── Validation ────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate(raw: dict, global_event: str, global_host: str) -> dict | str:
    """Return a cleaned recipient dict, or an error string on failure."""
    name  = str(raw.get("name",  "")).strip()
    email = str(raw.get("email", "")).strip()
    event = str(raw.get("event", global_event)).strip() or global_event
    host  = str(raw.get("host",  global_host)).strip()  or global_host

    if not name:
        return "Missing name"
    if not email or not _EMAIL_RE.match(email):
        return f"Invalid email address: {email!r}"
    if not event:
        return "Missing event name — provide it in the form or add an 'Event' column"
    if not host:
        return "Missing host name — provide it in the form or add a 'Host' column"

    return {"name": name, "email": email, "event": event, "host": host}

# ── HTTP handler (Vercel Python runtime) ──────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    """Vercel serverless handler. Class name must be exactly 'handler'."""

    def log_message(self, format, *args):  # noqa: A002
        pass  # Suppress BaseHTTPRequestHandler's default stderr output

    # ── CORS ─────────────────────────────────────────────────────────────────

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ── Health check ──────────────────────────────────────────────────────────

    def do_GET(self):
        self._respond(200, {"service": "MLSA Certificate Generator", "status": "ok"})

    # ── Main handler ──────────────────────────────────────────────────────────

    def do_POST(self):
        # 1. Parse request body
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            data   = json.loads(body)
        except (ValueError, json.JSONDecodeError):
            return self._respond(400, {"error": "Request body must be valid JSON"})

        raw_recipients = data.get("recipients", [])
        global_event   = str(data.get("event", "")).strip()
        global_host    = str(data.get("host",  "")).strip()

        # 2. Basic input checks
        if not isinstance(raw_recipients, list) or not raw_recipients:
            return self._respond(400, {"error": "'recipients' must be a non-empty list"})

        if len(raw_recipients) > 100:
            return self._respond(400, {"error": "Maximum 100 recipients per request"})

        # 3. Process each recipient
        results: list[dict] = []

        for raw in raw_recipients:
            validated = _validate(raw, global_event, global_host)

            if isinstance(validated, str):
                results.append({
                    "name":    str(raw.get("name",  "")),
                    "email":   str(raw.get("email", "")),
                    "status":  "error",
                    "message": validated,
                })
                continue

            name  = validated["name"]
            email = validated["email"]
            event = validated["event"]
            host  = validated["host"]

            try:
                cert_html  = render_certificate(name, event, host)
                pdf_bytes  = html_to_pdf(cert_html)
                email_html = render_email(name, event)
                send_email(email, name, event, pdf_bytes, email_html)
                results.append({"name": name, "email": email, "status": "sent"})

            except Exception as exc:  # noqa: BLE001
                results.append({
                    "name":    name,
                    "email":   email,
                    "status":  "error",
                    "message": str(exc),
                })

        self._respond(200, {"results": results})

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _respond(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",   "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)
