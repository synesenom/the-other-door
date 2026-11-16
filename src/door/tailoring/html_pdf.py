"""Print an HTML page to a PDF with the pinned Chromium headless shell, sealed (#165).

The seal stands where `tex_guard` stands for LaTeX: a model wrote the page, so the browser
gets nothing to reach. JavaScript is off (`Emulation.setScriptExecutionDisabled`), the page is
served by a loopback server over one folder (127.0.0.1, a random port, only files whose resolved
path is under the folder), and every request that is not on that origin is failed through
`Fetch` (`file:`, `blob:`, `ws:`, `data:` and other hosts and ports included). The browser runs
with a fresh profile that is removed afterwards, under a hard time limit, and is killed with its
children whatever happens. No Node: `door.tailoring.cdp` speaks the protocol.
"""

from __future__ import annotations

import argparse
import base64
import http.server
import mimetypes
import os
import platform as _platform
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

from door.core import chromium
from door.tailoring import cdp

A4_INCHES = (8.27, 11.69)


class PrintError(Exception):
    """The page could not be printed."""


class _Handler(http.server.BaseHTTPRequestHandler):
    root: Path

    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        path = unquote(urlsplit(self.path).path)
        target = (self.root / path.lstrip("/")).resolve()
        if not target.is_relative_to(self.root) or not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        pass


def _serve(folder: Path) -> http.server.ThreadingHTTPServer:
    handler = type("Handler", (_Handler,), {"root": Path(folder).resolve()})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _browser_args(exe: str, profile: str, *, system: str | None = None, euid: int | None = None, env=None) -> list[str]:
    system = system if system is not None else _platform.system()
    env = os.environ if env is None else env
    if euid is None and hasattr(os, "geteuid"):
        euid = os.geteuid()
    args = [exe, "--headless", "--remote-debugging-port=0", f"--user-data-dir={profile}", "--disable-gpu",
            "--no-first-run", "--no-default-browser-check", "about:blank"]
    if (system == "Linux" and euid == 0) or env.get("DOOR_CHROMIUM_NO_SANDBOX") == "1":
        args.insert(1, "--no-sandbox")  # a root or container process cannot use the sandbox; JS is off and only local files are served
    return args


STDERR_LOG = "door-stderr.log"  # in the throwaway profile: what Chromium said, for an early exit's error


def _launch(args: list[str]) -> subprocess.Popen:
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" else {"start_new_session": True}
    profile = next(a.split("=", 1)[1] for a in args if a.startswith("--user-data-dir="))
    with open(Path(profile) / STDERR_LOG, "wb") as log:
        return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log, **kwargs)


def _kill_tree(proc) -> None:
    """The browser and its children."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=15, stdin=subprocess.DEVNULL)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.wait(timeout=5)
    except (OSError, subprocess.SubprocessError, AttributeError):
        pass


def _wait_port(proc, profile: Path, deadline: float) -> tuple[int, str]:
    port_file = profile / "DevToolsActivePort"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            try:
                said = (profile / STDERR_LOG).read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
            except OSError:
                said = []
            raise PrintError("Chromium exited before it was ready (on Linux, run `./door doctor` for missing libraries)"
                             + (": " + " | ".join(said) if said else ""))
        try:
            lines = port_file.read_text(encoding="utf-8").splitlines()
            if len(lines) >= 2:
                return int(lines[0]), lines[1]
        except (OSError, ValueError):
            pass
        time.sleep(0.05)
    raise PrintError("Chromium did not finish starting in time")


def print_html(folder: Path, html: str, out_pdf: Path, *, timeout: float = 60.0, launcher=_launch) -> None:
    """Print `html` (written as `folder/index.html`, with the folder's other files beside it) to `out_pdf`."""
    exe = chromium.find_chromium()
    if exe is None:
        raise PrintError("no Chromium headless shell found; run `./door doctor --fix`")
    folder = Path(folder)
    (folder / "index.html").write_text(html, encoding="utf-8")
    deadline = time.monotonic() + timeout

    def left() -> float:
        return max(deadline - time.monotonic(), 0.1)

    profile = Path(tempfile.mkdtemp(prefix="door-chromium-"))
    server = _serve(folder)
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    proc = None
    conn = None
    try:
        proc = launcher(_browser_args(exe, str(profile)))
        port, path = _wait_port(proc, profile, deadline)
        conn = cdp.Cdp.connect(f"ws://127.0.0.1:{port}{path}", timeout=left())
        target = conn.send("Target.createTarget", {"url": "about:blank"}, timeout=left())["targetId"]
        sid = conn.send("Target.attachToTarget", {"targetId": target, "flatten": True}, timeout=left())["sessionId"]

        def paused(params: dict, session: str | None) -> None:
            url = params.get("request", {}).get("url", "")
            rid = params["requestId"]
            if url == origin or url.startswith(origin + "/"):
                conn.post("Fetch.continueRequest", {"requestId": rid}, session_id=session)
            elif params.get("resourceType") == "Document":
                # a page that navigates away (meta refresh, a link, a frame) stays where it is: an empty 204 is no navigation
                conn.post("Fetch.fulfillRequest", {"requestId": rid, "responseCode": 204}, session_id=session)
            else:
                conn.post("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"}, session_id=session)

        conn.on("Fetch.requestPaused", paused)
        conn.send("Emulation.setScriptExecutionDisabled", {"value": True}, session_id=sid, timeout=left())
        conn.send("Fetch.enable", {"patterns": [{"urlPattern": "*"}]}, session_id=sid, timeout=left())
        conn.send("Page.enable", session_id=sid, timeout=left())
        conn.send("Page.setLifecycleEventsEnabled", {"enabled": True}, session_id=sid, timeout=left())
        nav = conn.send("Page.navigate", {"url": f"{origin}/index.html"}, session_id=sid, timeout=left())
        if nav.get("errorText"):
            raise PrintError(f"the page did not load: {nav['errorText']}")
        while True:  # the blank page's own events come first: only this navigation's networkIdle counts
            event = conn.wait_event("Page.lifecycleEvent", timeout=left())
            if event.get("name") == "networkIdle" and event.get("loaderId") == nav.get("loaderId"):
                break
        result = conn.send("Page.printToPDF", {
            "preferCSSPageSize": True, "printBackground": True,
            "paperWidth": A4_INCHES[0], "paperHeight": A4_INCHES[1],
            "marginTop": 0, "marginBottom": 0, "marginLeft": 0, "marginRight": 0,
        }, session_id=sid, timeout=left())
        Path(out_pdf).write_bytes(base64.b64decode(result["data"]))
    except cdp.CdpTimeout as exc:
        raise PrintError(f"Chromium did not finish printing in {timeout:g} s ({exc})") from exc
    except cdp.CdpError as exc:
        raise PrintError(f"Chromium could not print the page: {exc}") from exc
    except OSError as exc:
        raise PrintError(f"printing failed: {exc}") from exc
    finally:
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        if proc is not None:
            _kill_tree(proc)
        server.shutdown()
        server.server_close()
        shutil.rmtree(profile, ignore_errors=True)


_TEST_PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
@page { size: A4; margin: 20mm }
body { font-family: sans-serif }
</style></head><body><h1>The other door</h1><p>A page printed by Chromium.</p></body></html>"""


def main(argv: list[str] | None = None) -> int:
    """Print a fixed test page (the install test's and the bundle check's proof that printing works)."""
    parser = argparse.ArgumentParser(prog="python -m door.tailoring.html_pdf")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="door-print-") as folder:
        try:
            print_html(Path(folder), _TEST_PAGE, args.out)
        except PrintError as exc:
            sys.stderr.write(f"print: {exc}\n")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
