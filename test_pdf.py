"""
test_pdf.py — Quick local test for PDF certificate generation.

Usage:
    python test_pdf.py
    python test_pdf.py "Jane Doe" "Azure Fundamentals" "John Smith"

Generates test_output.pdf in the project root and opens it automatically.
"""

import importlib.util
import os
import pathlib
import subprocess
import sys



# ── Load api/send.py without importing as a package ──────────────────────────

HERE = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("api_send", HERE / "api" / "send.py")
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

render_certificate_for_pdf = mod.render_certificate_for_pdf
# html_to_pdf                = mod.html_to_pdf

def html_to_pdf(html: str) -> bytes:
    try:
        # from xhtml2pdf import pisa  # type: ignore
        from weasyprint import HTML
    except ImportError as exc:
        raise RuntimeError(
            "WeasyPrint is not installed. Run: pip install weasyprint"
        ) from exc

    import io
    import os

    os.add_dll_directory(r"C:\Program Files (x86)\gtk-3.8.1")

    buf = io.BytesIO()
    HTML(string=html).write_pdf(buf)
    return buf.getvalue()

# ── Test data ─────────────────────────────────────────────────────────────────

name  = sys.argv[1] if len(sys.argv) > 1 else "Jane Doe"
event = sys.argv[2] if len(sys.argv) > 2 else "Azure Fundamentals Workshop"
host  = sys.argv[3] if len(sys.argv) > 3 else "John Smith"

print(f"Generating PDF for: {name!r} | {event!r} | {host!r}")

# ── Generate ──────────────────────────────────────────────────────────────────

html      = render_certificate_for_pdf(name, event, host)
# save html to a file for debugging
html_path = HERE / "test_output.html"
html_path.write_text(html, encoding="utf-8")

pdf_bytes = html_to_pdf(html)

out_path = HERE / "test_output.pdf"
out_path.write_bytes(pdf_bytes)

print(f"✓ Saved {len(pdf_bytes):,} bytes → {out_path}")

# ── Open the PDF automatically ────────────────────────────────────────────────

if sys.platform == "win32":
    os.startfile(str(out_path))
elif sys.platform == "darwin":
    subprocess.run(["open", str(out_path)])
else:
    subprocess.run(["xdg-open", str(out_path)])
