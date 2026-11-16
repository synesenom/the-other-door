"""`print_html` (#165): the sealed print, against a fake browser that speaks DevToolsActivePort and CDP."""

from __future__ import annotations

import base64
import http.client
import os
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from door.core import chromium
from door.tailoring import html_pdf
from door.tailoring.html_pdf import PrintError
from ws_fake import FakeWs

PDF = b"%PDF-1.4 fake"

BLOCKED = [
    "https://example.com/x.png", "http://127.0.0.1:1/other-port", "file:///etc/passwd",
    "blob:http://x/1", "ws://127.0.0.1:2/", "data:image/svg+xml,<svg/>", "http://127.0.0.1.evil.test/a",
]


class Fake:
    """What the fake browser saw and was told to do."""

    def __init__(self):
        self.commands: list[dict] = []
        self.args: list[str] = []
        self.profile: Path | None = None
        self.statuses: dict[str, int] = {}
        self.bodies: dict[str, bytes] = {}
        self.origin = ""
        self.paused: list[str] = []
        self.paused_types: dict[str, str] = {}
        self.pdf_error = False
        self.nav_error = ""
        self.hang = False
        self.servers: list[FakeWs] = []
        self.proc = type("P", (), {"poll": lambda self: None, "pid": 1})()
        self.probe_paths: list[str] = []

    def launcher(self, args):
        self.args = list(args)
        profile = Path(next(a.split("=", 1)[1] for a in args if a.startswith("--user-data-dir=")))
        self.profile = profile
        ws = FakeWs(self._script)
        self.servers.append(ws)
        (profile / "DevToolsActivePort").write_text(f"{ws.port}\n/devtools/browser/abc")
        return self.proc

    def _fetch(self, path):
        host, port = urlsplit(self.origin).hostname, urlsplit(self.origin).port
        c = http.client.HTTPConnection(host, port, timeout=5)
        c.request("GET", path)
        r = c.getresponse()
        self.statuses[path] = r.status
        self.bodies[path] = r.read()
        c.close()

    def _script(self, conn):
        while True:
            msg = conn.read_json()
            self.commands.append(msg)
            m, mid = msg["method"], msg["id"]
            if self.hang and m == "Page.navigate":
                import time

                time.sleep(30)
            if m == "Target.createTarget":
                conn.send_json({"id": mid, "result": {"targetId": "T1"}})
            elif m == "Target.attachToTarget":
                conn.send_json({"id": mid, "result": {"sessionId": "S1"}})
            elif m == "Page.navigate":
                url = msg["params"]["url"]
                self.origin = url.rsplit("/", 1)[0]
                conn.send_json({"id": mid, "result": {"frameId": "F", "loaderId": "L1", **({"errorText": self.nav_error} if self.nav_error else {})}})
                # the blank page's own networkIdle, which a print must not wait for
                conn.send_json({"method": "Page.lifecycleEvent", "sessionId": "S1", "params": {"name": "networkIdle", "loaderId": "L0"}})
                for path in ["/index.html", *self.probe_paths]:
                    self._fetch(path)
                for i, url in enumerate(self.paused):
                    conn.send_json({"method": "Fetch.requestPaused", "sessionId": "S1",
                                    "params": {"requestId": f"r{i}", "request": {"url": url},
                                               "resourceType": self.paused_types.get(url, "Image")}})
                conn.send_json({"method": "Page.lifecycleEvent", "sessionId": "S1", "params": {"name": "load", "loaderId": "L1"}})
                conn.send_json({"method": "Page.lifecycleEvent", "sessionId": "S1", "params": {"name": "networkIdle", "loaderId": "L1"}})
            elif m == "Page.printToPDF":
                if self.pdf_error:
                    conn.send_json({"id": mid, "error": {"message": "printing failed"}})
                else:
                    conn.send_json({"id": mid, "result": {"data": base64.b64encode(PDF).decode()}})
            else:
                conn.send_json({"id": mid, "result": {}})

    def methods(self):
        return [c["method"] for c in self.commands]

    def close(self):
        for s in self.servers:
            s.close()


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    killed = []
    monkeypatch.setattr(chromium, "find_chromium", lambda home=None: "/fake/chrome-headless-shell")
    monkeypatch.setattr(html_pdf, "_kill_tree", lambda proc: killed.append(proc))
    f.killed = killed
    yield f
    f.close()


def _print(fake, tmp_path, html="<p>hi</p>", **kw):
    folder = tmp_path / "work"
    folder.mkdir(exist_ok=True)
    out = tmp_path / "out.pdf"
    html_pdf.print_html(folder, html, out, launcher=fake.launcher, **kw)
    return folder, out


def test_a_page_is_printed_to_the_pdf_as_a4_with_css_page_size(fake, tmp_path):
    _, out = _print(fake, tmp_path)
    assert out.read_bytes() == PDF
    assert fake.methods().index("Page.printToPDF") > fake.methods().index("Page.navigate")
    pdf = next(c for c in fake.commands if c["method"] == "Page.printToPDF")
    assert pdf["sessionId"] == "S1"
    p = pdf["params"]
    assert p["preferCSSPageSize"] is True and p["printBackground"] is True
    assert (p["paperWidth"], p["paperHeight"]) == (8.27, 11.69)


def test_javascript_is_off_and_every_request_is_intercepted_before_navigation(fake, tmp_path):
    _print(fake, tmp_path)
    methods = fake.methods()
    off = next(c for c in fake.commands if c["method"] == "Emulation.setScriptExecutionDisabled")
    assert off["params"]["value"] is True
    fetch = next(c for c in fake.commands if c["method"] == "Fetch.enable")
    assert fetch["params"]["patterns"] == [{"urlPattern": "*"}]
    assert methods.index("Emulation.setScriptExecutionDisabled") < methods.index("Page.navigate")
    assert methods.index("Fetch.enable") < methods.index("Page.navigate")


def test_only_the_loopback_origin_is_continued_every_other_url_is_failed(fake, tmp_path):
    fake.paused = [*BLOCKED]
    # the origin is known only after the navigation, so the fake adds its own origin urls below
    _print(fake, tmp_path)
    failed = [c for c in fake.commands if c["method"] == "Fetch.failRequest"]
    assert len(failed) == len(BLOCKED)
    assert not [c for c in fake.commands if c["method"] == "Fetch.continueRequest"]
    assert all(c["sessionId"] == "S1" for c in failed)


def test_a_blocked_navigation_gets_an_empty_204_so_the_page_stays_and_prints(fake, tmp_path):
    fake.paused = ["http://other.test/refresh"]
    fake.paused_types = {"http://other.test/refresh": "Document"}
    _, out = _print(fake, tmp_path)
    fulfilled = [c for c in fake.commands if c["method"] == "Fetch.fulfillRequest"]
    assert [c["params"] for c in fulfilled] == [{"requestId": "r0", "responseCode": 204}]
    assert not [c for c in fake.commands if c["method"] == "Fetch.failRequest"]
    assert out.read_bytes() == PDF


def test_thousands_of_blocked_requests_do_not_overflow_the_stack(fake, tmp_path):
    fake.paused = [f"https://example.invalid/{i}.png" for i in range(2000)]
    _, out = _print(fake, tmp_path)
    assert len([c for c in fake.commands if c["method"] == "Fetch.failRequest"]) == 2000
    assert out.read_bytes() == PDF


def test_a_url_on_the_loopback_origin_is_continued(fake, tmp_path, monkeypatch):
    real = fake._script

    def script(conn):
        # wrap: replace the paused list once the origin is known
        orig_fetch = fake._fetch

        def fetch(path):
            orig_fetch(path)
            fake.paused = [fake.origin + "/index.html", fake.origin + "/photo.jpg", fake.origin + ".evil/x"]

        fake._fetch = fetch
        real(conn)

    fake._script = script
    _print(fake, tmp_path)
    cont = [c for c in fake.commands if c["method"] == "Fetch.continueRequest"]
    failed = [c for c in fake.commands if c["method"] == "Fetch.failRequest"]
    assert [c["params"]["requestId"] for c in cont] == ["r0", "r1"]
    assert [c["params"]["requestId"] for c in failed] == ["r2"]


def test_the_server_is_loopback_serves_the_page_and_only_files_under_the_folder(fake, tmp_path):
    (tmp_path / "secret.txt").write_text("outside")
    work = tmp_path / "work"
    work.mkdir()
    (work / "style.css").write_text("p{color:red}")
    (work / "out-link").symlink_to(tmp_path / "secret.txt") if hasattr(os, "symlink") else None
    fake.probe_paths = ["/style.css", "/../secret.txt", "/%2e%2e/secret.txt", "/out-link", "/missing", "/"]
    _print(fake, tmp_path, html="<p>the page</p>")
    assert urlsplit(fake.origin).hostname == "127.0.0.1"
    assert fake.statuses["/index.html"] == 200 and b"the page" in fake.bodies["/index.html"]
    assert fake.statuses["/style.css"] == 200 and fake.bodies["/style.css"] == b"p{color:red}"
    for blocked in ("/../secret.txt", "/%2e%2e/secret.txt", "/out-link", "/missing", "/"):
        assert fake.statuses[blocked] == 404, blocked
        assert b"outside" not in fake.bodies[blocked]


def test_the_server_is_closed_after_the_print(fake, tmp_path):
    _print(fake, tmp_path)
    port = urlsplit(fake.origin).port
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


def _cleaned(fake):
    assert fake.killed == [fake.proc]
    assert not fake.profile.exists()


def test_profile_removed_and_process_killed_on_success(fake, tmp_path):
    _print(fake, tmp_path)
    _cleaned(fake)


def test_profile_removed_and_process_killed_on_a_cdp_error(fake, tmp_path):
    fake.pdf_error = True
    with pytest.raises(PrintError, match="printing failed"):
        _print(fake, tmp_path)
    _cleaned(fake)
    assert not (tmp_path / "out.pdf").exists()


def test_a_page_that_does_not_load_is_a_print_error(fake, tmp_path):
    fake.nav_error = "net::ERR_FAILED"
    with pytest.raises(PrintError, match="did not load: net::ERR_FAILED"):
        _print(fake, tmp_path)
    _cleaned(fake)


def test_a_pdf_that_cannot_be_written_is_a_print_error(fake, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    with pytest.raises(PrintError, match="printing failed"):
        html_pdf.print_html(folder, "<p/>", tmp_path / "no-such-dir" / "out.pdf", launcher=fake.launcher)
    _cleaned(fake)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.skipif(sys.platform == "win32", reason="the POSIX process group; Windows uses taskkill /T")
def test_kill_tree_ends_the_browser_and_its_children(tmp_path):
    child_pid = tmp_path / "child.pid"
    code = (
        "import subprocess, sys, time, pathlib\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"pathlib.Path({str(child_pid)!r}).write_text(str(c.pid))\n"
        "time.sleep(60)\n"
    )
    proc = html_pdf._launch([sys.executable, "-c", code])
    deadline = time.monotonic() + 15
    while not child_pid.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    grandchild = int(child_pid.read_text())
    assert _alive(proc.pid) and _alive(grandchild)
    html_pdf._kill_tree(proc)
    deadline = time.monotonic() + 5
    while _alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert proc.poll() is not None
    assert not _alive(grandchild)


def test_a_hung_browser_times_out_and_is_cleaned_up(fake, tmp_path):
    fake.hang = True
    with pytest.raises(PrintError, match="did not finish"):
        _print(fake, tmp_path, timeout=1.5)
    _cleaned(fake)


def test_a_browser_that_never_opens_its_port_is_a_print_error(tmp_path, monkeypatch):
    monkeypatch.setattr(chromium, "find_chromium", lambda home=None: "/fake/c")
    killed = []
    monkeypatch.setattr(html_pdf, "_kill_tree", lambda proc: killed.append(proc))
    dead = type("P", (), {"poll": lambda self: 1, "pid": 2})()
    with pytest.raises(PrintError, match="exited"):
        html_pdf.print_html(tmp_path, "<p/>", tmp_path / "o.pdf", launcher=lambda args: dead, timeout=5)
    assert killed == [dead]


def test_no_chromium_names_doctor_fix(tmp_path, monkeypatch):
    monkeypatch.setattr(chromium, "find_chromium", lambda home=None: None)
    with pytest.raises(PrintError, match="doctor --fix"):
        html_pdf.print_html(tmp_path, "<p/>", tmp_path / "o.pdf")


@pytest.mark.parametrize("system,euid,env,expected", [
    ("Linux", 0, {}, True),
    ("Linux", 1000, {}, False),
    ("Linux", 1000, {"DOOR_CHROMIUM_NO_SANDBOX": "1"}, True),
    ("Darwin", 0, {}, False),
    ("Windows", None, {}, False),
])
def test_no_sandbox_only_as_root_on_linux_or_when_asked(system, euid, env, expected):
    args = html_pdf._browser_args("/x/chrome", "/tmp/p", system=system, euid=euid, env=env)
    assert ("--no-sandbox" in args) is expected
    assert "--remote-debugging-port=0" in args and "--user-data-dir=/tmp/p" in args
    assert args[0] == "/x/chrome"


def test_main_prints_a_test_page(fake, tmp_path, monkeypatch):
    seen = {}


    def fake_print(folder, html, out, **kw):
        seen["html"] = html
        Path(out).write_bytes(PDF)

    monkeypatch.setattr(html_pdf, "print_html", fake_print)
    out = tmp_path / "t.pdf"
    assert html_pdf.main(["--out", str(out)]) == 0
    assert out.read_bytes() == PDF and "<html" in seen["html"]

    def boom(*a, **k):
        raise PrintError("no browser")

    monkeypatch.setattr(html_pdf, "print_html", boom)
    assert html_pdf.main(["--out", str(out)]) == 1
