"""The phone server under The other door's control (#444, the desktop app's "Set up your phone"; #424, Claude Code's).

For one data folder: start `door serve` and a Cloudflare quick tunnel a phone can reach (nothing to install; its
address changes on restart), keep a Mac awake while it serves, pair one phone by a QR code, and stop it all again. What was started is in `<home>/.serve/run.json`, its logs in
`<home>/logs/`; the processes are their own, so serving outlives the app or the conversation that
started it. Every process, HTTP call and CLI is a parameter, so tests run none of them.
"""

from __future__ import annotations

import io
import json
import os
import re
import socket
import sys
import tarfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from door.core import process, utils, workspace
from door.core.downloads import pinned
from door import version
from door.core.phone import pairing

DEFAULT_PORT = 8765
CLOUDFLARED_VERSION = "2026.10.6"
# The release's own digests (github.com/cloudflare/cloudflared/releases), checked before anything runs.
CLOUDFLARED = {
    "darwin-arm64": ("cloudflared-darwin-arm64.tgz", "ea1e5105d35bbe16cee5b2f7b4742059ada341fbd35938ed827c24b85efa51c8"),
    "linux-x86_64": ("cloudflared-linux-amd64", "1d356dac769d0dbf62ebe588c4034824bbff98d5790c2f844cc99e0e2f57462d"),
    "windows-x86_64": ("cloudflared-windows-amd64.exe", "d521b3bf68982165f0d06d76732f22d9a105ef057ff3ae4c0986f3a23190950f"),
}
# The digest of the cloudflared program itself (the macOS download is an archive, so its own digest differs).
CLOUDFLARED_BINARY_SHA256 = {
    "darwin-arm64": "380451015c3676789adc4200f43757e950e7173b920b0094e272e8bea59d7927",
    "linux-x86_64": CLOUDFLARED["linux-x86_64"][1],
    "windows-x86_64": CLOUDFLARED["windows-x86_64"][1],
}
_TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


# ----------------------------------------------------------------------------- the real world
PUBLISHED_TIMEOUT = 2  # seconds for one public DNS answer; 40 tries keep the whole wait under two minutes


def _published(host: str) -> bool:
    """Whether public DNS knows `host` yet, asked of Cloudflare's resolver over HTTPS: this computer's own
    resolver would remember a too-early "not found" for a while."""
    import requests

    try:
        r = requests.get("https://cloudflare-dns.com/dns-query", params={"name": host, "type": "A"},
                         headers={"accept": "application/dns-json"}, timeout=PUBLISHED_TIMEOUT)
        return r.ok and bool(r.json().get("Answer"))
    except (requests.RequestException, ValueError):
        return False


def _answers(url: str) -> bool:
    import requests

    try:
        return requests.get(f"{url.rstrip('/')}/manifest.webmanifest", timeout=5).ok
    except requests.RequestException:
        return False


def _bin_dir() -> Path:
    return Path.home() / ".local" / "bin"


def _system_key(platform: str | None = None, machine: str | None = None) -> str:
    import platform as platform_mod

    system = {"darwin": "darwin", "win32": "windows"}.get(platform or sys.platform, "linux")
    return f"{system}-{_arch(machine or platform_mod.machine())}"


def find_cloudflared(*, binaries: dict = CLOUDFLARED_BINARY_SHA256, platform: str | None = None,
                     machine: str | None = None) -> str | None:
    """The cloudflared of the DOOR_BIN folder or ~/.local/bin whose sha256 is the pinned one, else None
    (`start` then downloads the pinned one over it). A cloudflared of PATH, or any other copy, is never run."""
    digest = binaries.get(_system_key(platform, machine))
    if digest is None:
        return None
    name = "cloudflared.exe" if (platform or sys.platform) == "win32" else "cloudflared"
    for folder in filter(None, (os.environ.get("DOOR_BIN"), str(_bin_dir()))):
        path = Path(folder) / name
        if path.is_file() and pinned.sha256(path) == digest:
            return str(path)
    return None


def default_web_dir() -> Path:
    return Path(os.environ.get("DOOR_WEB_DIR") or workspace.REPO_ROOT / "app" / "out" / "web")


def _defaults() -> dict:
    return {
        "spawn": process.spawn_detached, "is_alive": process.is_alive, "kill": process.kill_tree, "answers": _answers, "published": _published,
        "sleep": time.sleep, "platform": sys.platform, "find_cloudflared": find_cloudflared,
        "web_dir": default_web_dir(),
    }


# ----------------------------------------------------------------------------- cloudflared
def _arch(machine: str) -> str:
    return "arm64" if machine.lower() in ("arm64", "aarch64") else "x86_64"


def install_cloudflared(dest: Path | None = None, *, platform: str | None = None, machine: str | None = None,
                        pins: dict = CLOUDFLARED) -> Path:
    """Download the pinned cloudflared for this system, check its digest, put it in `dest` (~/.local/bin)."""
    system = {"darwin": "darwin", "win32": "windows"}.get(platform or sys.platform, "linux")
    key = _system_key(platform, machine)
    if key not in pins:
        raise ValueError(f"no cloudflared for {key}; install it yourself (https://github.com/cloudflare/cloudflared)")
    asset, digest = pins[key]
    url = f"https://github.com/cloudflare/cloudflared/releases/download/{CLOUDFLARED_VERSION}/{asset}"
    dest = Path(dest or _bin_dir())
    target = dest / ("cloudflared.exe" if system == "windows" else "cloudflared")
    with utils.staging(dest, ".cloudflared.") as staging:
        pinned.download([(url, asset, digest)], staging)
        staged = staging / target.name
        if asset.endswith(".tgz"):
            with tarfile.open(staging / asset, mode="r:gz") as tar:
                member = next(m for m in tar.getmembers() if Path(m.name).name == "cloudflared" and m.isfile())
                staged.write_bytes(tar.extractfile(member).read())
        else:
            (staging / asset).rename(staged)
        staged.chmod(0o755)
        staged.replace(target)
    return target


# ----------------------------------------------------------------------------- state
def _run_file(home: Path) -> Path:
    return Path(home) / ".serve" / "run.json"


def _read_run(home: Path) -> dict | None:
    return process.read_run(_run_file(home))


def _write_run(home: Path, run: dict) -> None:
    process.write_run(_run_file(home), run)


def _free_port(start: int = DEFAULT_PORT) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("no free port for the phone server")


def status(home: Path, **deps) -> dict:
    """Whether this data folder is serving a phone, where, and which phone is paired.

    `outdated` says a live server was started by another version (or one that did not record it, #109):
    it answers with old code, so `start` replaces it; the app does so at its start.
    """
    d = {**_defaults(), **deps}
    run = _read_run(home)
    # A quick tunnel that died took its address with it: nothing is served then, and `start` brings it all back.
    running = bool(run and d["is_alive"](run["serve_pid"]) and (not run.get("tunnel_pid") or d["is_alive"](run["tunnel_pid"])))
    out = {
        "running": running,
        "devices": pairing.devices(Path(home)),
        "web_built": (Path(d["web_dir"]) / "index.html").is_file(),
    }
    if running:
        out.update(address=run["address"], port=run["port"], started_at=run.get("started_at"),
                   outdated=run.get("version") != version.VERSION)
    return out


def _wait(predicate, *, tries: int, sleep) -> bool:
    for _ in range(tries):
        if predicate():
            return True
        sleep(0.5)
    return False


def _stop_pids(run: dict, kill) -> None:
    for key in ("tunnel_pid", "awake_pid", "serve_pid"):
        if run.get(key):
            kill(run[key])


# The app's restart at its start and a Start pressed in Settings run on two threads of one server.
_LOCK = threading.RLock()


def start(home: Path, **deps) -> dict:
    with _LOCK:
        return _start(home, **deps)


def _start(home: Path, **deps) -> dict:
    """Serve this data folder to a phone through a Cloudflare quick tunnel; reuses a running one.

    Returns `status()`, or ``{"error"}``.
    """
    d = {**_defaults(), **deps}
    home = Path(home)
    current = status(home, **deps)
    if current["running"] and not current["outdated"]:
        return current
    if _read_run(home):
        stop(home, **deps)
    pairing.forget(home)  # a phone paired with a tunnel that died with the computer: its address is gone

    port = d.get("port") or _free_port()
    logs = home / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    env = process.door_env(home)
    serve = d["spawn"]([sys.executable, "-m", "door", "serve", "start", "--port", str(port), "--web", str(d["web_dir"])],
                       log=logs / "serve.log", env=env)
    run = {"serve_pid": serve.pid, "port": port, "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
           "version": version.VERSION}
    local = f"http://127.0.0.1:{port}"
    if not _wait(lambda: d["answers"](local), tries=60, sleep=d["sleep"]):
        _stop_pids(run, d["kill"])
        return {"error": f"The other door's server did not start; see {logs / 'serve.log'}"}
    if d["platform"] == "darwin":  # a sleeping Mac cannot answer a phone
        run["awake_pid"] = d["spawn"](["caffeinate", "-i", "-w", str(serve.pid)], log=logs / "awake.log").pid

    binary = d["find_cloudflared"]() or str(install_cloudflared())
    log = logs / "tunnel.log"
    if log.exists():
        log.unlink()
    run["tunnel_pid"] = d["spawn"]([binary, "tunnel", "--no-autoupdate", "--url", local], log=log).pid

    def address() -> str | None:
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        m = _TUNNEL_URL.search(text)
        return m.group(0) if m else None

    if not _wait(lambda: address() is not None, tries=120, sleep=d["sleep"]):
        _stop_pids(run, d["kill"])
        return {"error": f"the tunnel gave no address; see {log}"}
    # Ready when Cloudflare has registered the connection. The new name is not looked up from here:
    # a lookup before it exists is remembered as missing by this computer's resolver for a while.
    registered = lambda: "Registered tunnel connection" in log.read_text(encoding="utf-8", errors="replace")  # noqa: E731
    if not _wait(registered, tries=120, sleep=d["sleep"]):
        _stop_pids(run, d["kill"])
        return {"error": f"the tunnel could not connect to Cloudflare; see {log}"}
    # A phone that looks the new name up before public DNS has it gets "not found", and keeps that answer.
    # A network that blocks the check gets the address after the wait: the tunnel itself is up.
    url = address()
    host = url.removeprefix("https://")
    _wait(lambda: d["published"](host), tries=40, sleep=d["sleep"])
    run["address"] = url
    _write_run(home, run)
    return status(home, **deps)


def stop(home: Path, **deps) -> dict:
    """Stop what `start` started for this data folder."""
    with _LOCK:
        return _stop(home, **deps)


def _stop(home: Path, **deps) -> dict:
    d = {**_defaults(), **deps}
    run = _read_run(home)
    if not run:
        return {"stopped": False}
    _stop_pids(run, d["kill"])
    _run_file(home).unlink(missing_ok=True)
    pairing.forget(home)  # the tunnel's address dies with it, and the phone's pairing with the address
    return {"stopped": True}


def _qr_svg(text: str) -> str:
    import segno

    # A whole document, not svg_inline's: the window shows it as an image, which needs the SVG namespace.
    out = io.BytesIO()
    segno.make(text, error="m").save(out, kind="svg", scale=6, border=2, xmldecl=False)
    return out.getvalue().decode("utf-8")


def pair(home: Path, device: str, **deps) -> dict:
    """A QR code that pairs the phone (refused while one is paired): ``{"device", "qr_svg", "expires_at"}``. The code is only inside the
    QR (shown on this screen, scanned by the phone): never handed out as text."""
    current = status(home, **deps)
    if not current["running"]:
        return {"error": "The other door is not serving a phone yet; start it first"}
    try:
        code = pairing.new_code(Path(home), device, strong=True)
    except ValueError as exc:
        return {"error": str(exc)}
    qr = deps.get("qr") or _qr_svg
    svg = qr(f"{current['address']}/#pair={code}")
    return {"device": device.strip(), "qr_svg": svg,
            "expires_at": (datetime.now(UTC) + pairing.STRONG_TTL).isoformat(timespec="seconds")}


def remove(home: Path, device: str) -> dict:
    """Take a phone away: its token stops working at once, and it shows the pairing screen again."""
    if not pairing.unpair(Path(home), device):
        return {"error": f"no paired phone is called {device!r}"}
    return {"removed": device}
