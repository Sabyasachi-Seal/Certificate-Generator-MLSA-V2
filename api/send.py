"""
MLSA Certificate Generator — Serverless API
POST /api/send

Accepts a list of recipients (max 50), renders an HTML certificate for each one,
converts it to PDF with xhtml2pdf, then emails it via Gmail SMTP (or any SMTP
server) with the PDF attached.  A single SMTP connection is reused for the
whole batch to stay well within Vercel's function timeout.

Environment variables (set in Vercel dashboard or .env):
    SMTP_HOST      — SMTP server hostname          (default: smtp.gmail.com)
    SMTP_PORT      — SMTP port, STARTTLS           (default: 587)
    SMTP_USER      — Gmail address, e.g. you@gmail.com
    SMTP_PASSWORD  — Gmail App Password (16 chars, no spaces)
    EMAIL_FROM     — Display name + address, e.g. "Certs <you@gmail.com>"
                     Falls back to SMTP_USER when omitted.
"""

from __future__ import annotations

import json
import os
import re
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_RECIPIENTS = 50

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
        from xhtml2pdf import pisa  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "xhtml2pdf is not installed. Run: pip install xhtml2pdf"
        ) from exc

    import io

    buf = io.BytesIO()
    result = pisa.CreatePDF(
        src=html,
        dest=buf,
        encoding="utf-8",
        # Resolve relative assets (background.png, fonts) from the template dir
        path=str(CERT_DIR) + "/",
    )
    if result.err:
        raise RuntimeError(f"PDF generation failed with {result.err} error(s)")
    return buf.getvalue()

# ── SMTP helpers ──────────────────────────────────────────────────────────────

def _open_smtp() -> smtplib.SMTP:
    """Open and authenticate a single SMTP connection reused for the whole batch."""
    host     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port     = int(os.environ.get("SMTP_PORT", "587"))
    user     = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()

    if not user or not password:
        raise RuntimeError(
            "SMTP_USER and SMTP_PASSWORD environment variables must be set. "
            "For Gmail, use your Gmail address and a 16-character App Password "
            "(Google Account → Security → 2-Step Verification → App passwords)."
        )

    smtp = smtplib.SMTP(host, port, timeout=30)
    smtp.ehlo()
    smtp.starttls()
    smtp.ehlo()
    smtp.login(user, password)
    return smtp


def _build_message(
    from_addr: str,
    to_email: str,
    to_name: str,
    event: str,
    pdf_bytes: bytes,
    email_html: str,
) -> MIMEMultipart:
    safe_name = re.sub(r"[^\w\s-]", "", to_name).strip().replace(" ", "_")
    filename  = f"Certificate_{safe_name}.pdf"

    msg = MIMEMultipart("mixed")
    msg["From"]    = from_addr
    msg["To"]      = f"{to_name} <{to_email}>"
    msg["Subject"] = f"Your Certificate of Participation \u2013 {event}"

    msg.attach(MIMEText(email_html, "html", "utf-8"))

    pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
    pdf_part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(pdf_part)

    return msg


def _send_batch(validated: list[dict], smtp: smtplib.SMTP) -> list[dict]:
    """Send one email per recipient over an already-open SMTP connection."""
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    from_addr = os.environ.get("EMAIL_FROM", smtp_user).strip() or smtp_user

    results: list[dict] = []

    for r in validated:
        name  = r["name"]
        email = r["email"]
        event = r["event"]
        host  = r["host"]

        try:
            cert_html  = render_certificate(name, event, host)
            pdf_bytes  = html_to_pdf(cert_html)
            email_html = render_email(name, event)
            msg = _build_message(from_addr, email, name, event, pdf_bytes, email_html)
            smtp.sendmail(from_addr, [email], msg.as_string())
            results.append({"name": name, "email": email, "status": "sent"})

        except Exception as exc:  # noqa: BLE001
            results.append({
                "name":    name,
                "email":   email,
                "status":  "error",
                "message": str(exc),
            })

    return results

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

        if len(raw_recipients) > MAX_RECIPIENTS:
            return self._respond(400, {
                "error": (
                    f"Maximum {MAX_RECIPIENTS} recipients per request. "
                    f"You submitted {len(raw_recipients)}."
                )
            })

        # 3. Validate every recipient before opening SMTP
        validated: list[dict] = []
        pre_errors: list[dict] = []

        for raw in raw_recipients:
            result = _validate(raw, global_event, global_host)
            if isinstance(result, str):
                pre_errors.append({
                    "name":    str(raw.get("name",  "")),
                    "email":   str(raw.get("email", "")),
                    "status":  "error",
                    "message": result,
                })
            else:
                validated.append(result)

        # 4. Open one SMTP connection for the whole batch
        sent_results: list[dict] = []

        if validated:
            smtp = None
            try:
                smtp = _open_smtp()
                sent_results = _send_batch(validated, smtp)
            except Exception as exc:  # noqa: BLE001
                # Connection-level failure — mark all as errored
                msg = str(exc)
                sent_results = [
                    {"name": r["name"], "email": r["email"],
                     "status": "error", "message": msg}
                    for r in validated
                ]
            finally:
                if smtp:
                    try:
                        smtp.quit()
                    except Exception:  # noqa: BLE001
                        pass

        self._respond(200, {"results": pre_errors + sent_results})

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _respond(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",   "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)
