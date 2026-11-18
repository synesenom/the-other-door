"""Print an HTML page to a PDF with the pinned Chromium headless shell, sealed (#165).

The seal is the second layer after `html_guard`: a model wrote the page, so the browser
gets nothing to reach. JavaScript is off (`Emulation.setScriptExecutionDisabled`), the page is
served by a loopback server over one folder (127.0.0.1, a random port, only files whose resolved
path is under the folder), and every request that is not on that origin is failed through
`Fetch` (`file:`, `blob:`, `ws:`, `data:` and other hosts and ports included). The browser runs
with a fresh profile that is removed afterwards, under a hard time limit, and is killed with its
children whatever happens. No Node: `door.render.cdp` speaks the protocol.
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
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import unquote, urlsplit

from door.core import chromium, process
from door.render import cdp

A4_INCHES = (8.27, 11.69)


class PrintError(Exception):
    """The page could not be printed."""


class _Handler(http.server.BaseHTTPRequestHandler):
    root: Path
    page: bytes = b""
    assets: dict[str, dict[str, Path]] = {}

    def _target(self, path: str) -> tuple[Path, Path] | None:
        """``(file, folder it must stay inside)`` for a path: under an asset name, the one of its files of that exact
        name; else in the page's folder. None where no file can be meant."""
        first, _, rest = path.lstrip("/").partition("/")
        if first in self.assets:
            file = self.assets[first].get(rest)
            return (file, file.parent) if file else None
        return self.root / path.lstrip("/"), self.root

    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        target = None
        path = unquote(urlsplit(self.path).path)
        if path == "/index.html":
            self._send(self.page, "text/html; charset=utf-8")
            return
        try:
            where = self._target(path)
            if where:
                resolved = where[0].resolve()
                if resolved.is_relative_to(where[1]) and resolved.is_file():
                    target = resolved
        except (OSError, ValueError):
            pass
        if target is None:
            self.send_error(404)
            return
        self._send(target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")

    def _send(self, data: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        pass


def _serve(folder: Path, page: bytes, assets: dict[str, Sequence[Path]] | None = None) -> http.server.ThreadingHTTPServer:
    resolved = {name: {Path(f).name: Path(f).parent.resolve() / Path(f).name for f in files} for name, files in (assets or {}).items()}
    handler = type("Handler", (_Handler,), {"root": Path(folder).resolve(), "page": page, "assets": resolved})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _browser_args(exe: str, profile: str, *, system: str | None = None, euid: int | None = None,
                  no_sandbox: bool = False) -> list[str]:
    system = system if system is not None else _platform.system()
    if euid is None and hasattr(os, "geteuid"):
        euid = os.geteuid()
    args = [exe, "--headless", "--remote-debugging-port=0", f"--user-data-dir={profile}", "--disable-gpu",
            "--no-first-run", "--no-default-browser-check", "about:blank"]
    if no_sandbox or (system == "Linux" and euid == 0):
        # root cannot use the sandbox, and Ubuntu 23.10+ refuses it to everyone else (print_html retries without it);
        # JavaScript is off and nothing but the folder's own files is served
        args.insert(1, "--no-sandbox")
    return args


STDERR_LOG = "door-stderr.log"  # in the throwaway profile: what Chromium said, for an early exit's error


def _launch(args: list[str]) -> subprocess.Popen:
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" else {"start_new_session": True}
    profile = next(a.split("=", 1)[1] for a in args if a.startswith("--user-data-dir="))
    with open(Path(profile) / STDERR_LOG, "wb") as log:
        return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log, **kwargs)


def _kill_tree(proc) -> None:
    """The browser and its children."""
    process.kill_tree(proc.pid, getattr(signal, "SIGKILL", signal.SIGTERM))  # no SIGKILL on Windows: taskkill ends it
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


def _refused_sandbox(profile: Path) -> bool:
    """Chromium aborted because the OS gives it no sandbox (Ubuntu 23.10+ restricts user namespaces)."""
    try:
        return "No usable sandbox" in (profile / STDERR_LOG).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def print_html(folder: Path, html: str, out_pdf: Path, *,
               assets: dict[str, Sequence[Path]] | None = None, timeout: float = 60.0, launcher=_launch) -> None:
    """Print `html` (served from memory as `/index.html`, with the folder's files beside it) to `out_pdf`.

    `assets` maps one URL segment to files outside the page's folder (``{"fonts": [Path(".../x.ttf")]}`` serves
    ``/fonts/x.ttf``): shared files such as the fonts are served by their names, not copied into the job's folder.
    """
    exe = chromium.find_chromium()
    if exe is None:
        raise PrintError("no Chromium headless shell found; run `./door doctor --fix`")
    folder = Path(folder)
    deadline = time.monotonic() + timeout

    def left() -> float:
        return max(deadline - time.monotonic(), 0.1)

    profile = Path(tempfile.mkdtemp(prefix="door-chromium-"))
    server = _serve(folder, html.encode("utf-8"), assets)
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    proc = None
    conn = None
    try:
        proc = launcher(_browser_args(exe, str(profile)))
        try:
            port, path = _wait_port(proc, profile, deadline)
        except PrintError:
            if not _refused_sandbox(profile):
                raise
            proc = launcher(_browser_args(exe, str(profile), no_sandbox=True))
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
    parser = argparse.ArgumentParser(prog="python -m door.render.html_pdf")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds Chromium has to print")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="door-print-") as folder:
        try:
            print_html(Path(folder), _TEST_PAGE, args.out, timeout=args.timeout)
        except PrintError as exc:
            sys.stderr.write(f"print: {exc}\n")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
