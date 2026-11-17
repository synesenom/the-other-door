"""The offline suite's network guard (`tests/conftest.py` `_no_real_network`, #239): a download through `urllib`
(the pinned Chromium, the CV fonts: `pinned.http_get`) fails at once, as a `requests` call does, instead of
reaching the network. Loopback stays open: a test's own local server is no network."""

import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from door.core import pinned


def test_a_urllib_download_is_refused(tmp_path):
    with pytest.raises(AssertionError, match="offline test tried to reach the network"):
        pinned.http_get("https://example.com/chrome.zip", tmp_path / "chrome.zip")
    assert not (tmp_path / "chrome.zip").exists()


def test_a_urlopen_of_a_request_object_is_refused():
    with pytest.raises(AssertionError, match="https://example.com/"):
        urllib.request.urlopen(urllib.request.Request("https://example.com/", method="HEAD"), timeout=1)


def test_a_local_server_is_still_reached():
    class Answer(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Answer)
    threading.Thread(target=server.handle_request, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=5) as response:
            assert response.read() == b"ok"
    finally:
        server.server_close()
