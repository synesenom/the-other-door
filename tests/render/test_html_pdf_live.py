"""`print_html` with the real pinned Chromium headless shell (#165). Skipped where none is installed
(`./door doctor --fix`, or `DOOR_BIN`), or where it cannot start (a Linux without its libraries)."""

from __future__ import annotations

import http.server
import threading

import pypdfium2 as pdfium
import pytest

from door.core import chromium
from door.render.html_pdf import PrintError, print_html
from live_utils import not_reached

pytestmark = pytest.mark.live


class _Counter(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self):  # noqa: N802
        type(self).hits.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.end_headers()
        self.wfile.write(b"<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'/>")

    def log_message(self, *args):
        pass


def test_a_page_prints_with_scripts_off_and_nothing_fetched_from_elsewhere(tmp_path):
    if chromium.find_chromium() is None:
        pytest.skip("no Chromium headless shell installed (./door doctor --fix)")
    other = http.server.HTTPServer(("127.0.0.1", 0), type("H", (_Counter,), {"hits": []}))
    threading.Thread(target=other.serve_forever, daemon=True).start()
    hits = other.RequestHandlerClass.hits
    (tmp_path / "work").mkdir()
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>@page {{ size: A4; margin: 20mm }}</style></head>
<body><p id="p">Static text stays</p>
<script>document.getElementById('p').textContent = 'SCRIPT-RAN';</script>
<img src="http://127.0.0.1:{other.server_address[1]}/remote.svg"></body></html>"""
    out = tmp_path / "out.pdf"
    try:
        print_html(tmp_path / "work", html, out)
    except PrintError as exc:
        not_reached("chromium", str(exc))
    finally:
        other.shutdown()
    assert out.read_bytes().startswith(b"%PDF")
    pdf = pdfium.PdfDocument(str(out))
    text = pdf[0].get_textpage().get_text_range()
    pdf.close()
    assert "Static text stays" in text
    assert "SCRIPT-RAN" not in text
    assert hits == []
