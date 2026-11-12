"""The phone server under The other door's control (#444, the desktop app's "Set up your phone"; #424, Claude Code's).

For one data folder: start `door serve` and a connection a phone can reach (a Cloudflare quick tunnel,
nothing to install but its address changes on restart, or Tailscale for a lasting, private one), keep a Mac awake while it serves, pair a phone by a
QR code, and stop it all again. What was started is in `<home>/.serve/run.json`, its logs in
`<home>/logs/`; the processes are their own, so serving outlives the app or the conversation that
started it. Every process, HTTP call and CLI is a parameter, so tests run none of them.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path

from door.core import pairing, workspace

DEFAULT_PORT = 8765
CLOUDFLARED_VERSION = "2026.10.6"
# The release's own digests (github.com/cloudflare/cloudflared/releases), checked before anything runs.
CLOUDFLARED = {
    "darwin-x86_64": ("cloudflared-darwin-amd64.tgz", "6c04a13835ca5ff29a0c6f58d17d1f3956aad1b7df1631f5b5efbc06269deded"),
    "darwin-arm64": ("cloudflared-darwin-arm64.tgz", "ea1e5105d35bbe16cee5b2f7b4742059ada341fbd35938ed827c24b85efa51c8"),
    "linux-x86_64": ("cloudflared-linux-amd64", "1d356dac769d0dbf62ebe588c4034824bbff98d5790c2f844cc99e0e2f57462d"),
    "windows-x86_64": ("cloudflared-windows-amd64.exe", "d521b3bf68982165f0d06d76732f22d9a105ef057ff3ae4c0986f3a23190950f"),
}
TAILSCALE_DOWNLOAD = "https://tailscale.com/download"
_TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
_LINK = re.compile(r"https://login\.tailscale\.com/\S+")


# ----------------------------------------------------------------------------- the real world
def _spawn(argv: list[str], *, log: Path, env: dict | None = None):
    log.parent.mkdir(parents=True, exist_ok=True)
    out = open(log, "ab")  # noqa: SIM115 - handed to the child, which outlives this call
    extra = {"creationflags": 0x00000008 | 0x00000200} if sys.platform == "win32" else {"start_new_session": True}
    return subprocess.Popen(argv, stdout=out, stderr=out, stdin=subprocess.DEVNULL, env=env, **extra)


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _kill(pid: int) -> None:
    """End a process this module started, with everything it started: each runs in a session of its own
    (`_spawn`), and Python on a Mac starts the real server as a child of a launcher."""
    try:
        if sys.platform != "win32":
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def _answers(url: str) -> bool:
    import requests

    try:
        return requests.get(f"{url.rstrip('/')}/manifest.webmanifest", timeout=5).ok
    except requests.RequestException:
        return False


def _bin_dir() -> Path:
    return Path.home() / ".local" / "bin"


def find_cloudflared() -> str | None:
    """The bundled cloudflared (the packaged app's DOOR_BIN), else ~/.local/bin's, else PATH's."""
    name = "cloudflared.exe" if sys.platform == "win32" else "cloudflared"
    for folder in filter(None, (os.environ.get("DOOR_BIN"), str(_bin_dir()))):
        if (Path(folder) / name).is_file():
            return str(Path(folder) / name)
    return shutil.which("cloudflared")


def find_tailscale() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    mac_app = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
    return str(mac_app) if mac_app.is_file() else None


def default_web_dir() -> Path:
    return Path(os.environ.get("DOOR_WEB_DIR") or workspace.REPO_ROOT / "app" / "out" / "web")


def _defaults() -> dict:
    return {
        "spawn": _spawn, "is_alive": _is_alive, "kill": _kill, "run": subprocess.run, "answers": _answers,
        "sleep": time.sleep, "platform": sys.platform, "find_cloudflared": find_cloudflared,
        "find_tailscale": find_tailscale, "web_dir": default_web_dir(),
    }


# ----------------------------------------------------------------------------- cloudflared
def _arch(machine: str) -> str:
    return "arm64" if machine.lower() in ("arm64", "aarch64") else "x86_64"


def install_cloudflared(dest: Path | None = None, *, get=None, platform: str | None = None, machine: str | None = None,
                        pins: dict = CLOUDFLARED) -> Path:
    """Download the pinned cloudflared for this system, check its digest, put it in `dest` (~/.local/bin)."""
    import platform as platform_mod

    if get is None:
        import requests

        get = requests.get
    platform = platform or sys.platform
    system = {"darwin": "darwin", "win32": "windows"}.get(platform, "linux")
    key = f"{system}-{_arch(machine or platform_mod.machine())}"
    if key not in pins:
        raise ValueError(f"no cloudflared for {key}; install it yourself (https://github.com/cloudflare/cloudflared)")
    asset, digest = pins[key]
    url = f"https://github.com/cloudflare/cloudflared/releases/download/{CLOUDFLARED_VERSION}/{asset}"
    response = get(url, timeout=120)
    response.raise_for_status()
    blob = response.content
    if hashlib.sha256(blob).hexdigest() != digest:
        raise ValueError(f"the cloudflared download does not match its pinned checksum; nothing was installed ({url})")
    if asset.endswith(".tgz"):
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            member = next(m for m in tar.getmembers() if Path(m.name).name == "cloudflared" and m.isfile())
            blob = tar.extractfile(member).read()
    dest = Path(dest or _bin_dir())
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / ("cloudflared.exe" if system == "windows" else "cloudflared")
    target.write_bytes(blob)
    target.chmod(0o755)
    return target


# ----------------------------------------------------------------------------- state
def _run_file(home: Path) -> Path:
    return Path(home) / ".serve" / "run.json"


def _read_run(home: Path) -> dict | None:
    try:
        return json.loads(_run_file(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_run(home: Path, run: dict) -> None:
    path = _run_file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run, indent=2), encoding="utf-8")


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
    """Whether this data folder is serving a phone, where, over what, and which phones are paired."""
    d = {**_defaults(), **deps}
    run = _read_run(home)
    # A quick tunnel that died took its address with it: nothing is served then, and `start` brings it all back.
    running = bool(run and d["is_alive"](run["serve_pid"]) and (not run.get("tunnel_pid") or d["is_alive"](run["tunnel_pid"])))
    out = {
        "running": running,
        "devices": pairing.devices(Path(home)),
        "web_built": (Path(d["web_dir"]) / "index.html").is_file(),
        "tailscale_installed": d["find_tailscale"]() is not None,
    }
    if running:
        out.update(connection=run["connection"], address=run["address"], port=run["port"],
                   lasting=run["connection"] == "tailscale", started_at=run.get("started_at"))
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


def start(home: Path, connection: str, **deps) -> dict:
    """Serve this data folder to a phone over `connection` ("cloudflare" or "tailscale"); reuses a running one.

    Returns `status()`, or ``{"needs": "install_tailscale" | "sign_in_tailscale" | "enable_https", "link"}``
    for a step only the user can take, or ``{"error"}``.
    """
    d = {**_defaults(), **deps}
    home = Path(home)
    if connection not in ("cloudflare", "tailscale"):
        return {"error": f"unknown connection {connection!r} (cloudflare or tailscale)"}
    current = status(home, **deps)
    if current["running"] and current["connection"] == connection:
        return current
    stale = _read_run(home)
    if stale:
        stop(home, **deps)

    tailscale = None
    if connection == "tailscale":
        tailscale = d["find_tailscale"]()
        if not tailscale:
            return {"needs": "install_tailscale", "link": TAILSCALE_DOWNLOAD}
        state = json.loads(d["run"]([tailscale, "status", "--json"], capture_output=True, text=True).stdout or "{}")
        if state.get("BackendState") != "Running":
            return {"needs": "sign_in_tailscale", "link": TAILSCALE_DOWNLOAD}
        dns = (state.get("Self") or {}).get("DNSName", "").rstrip(".")

    port = d.get("port") or _free_port()
    logs = home / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "DOOR_HOME": str(home), "PYTHONPATH": str(workspace.REPO_ROOT / "src")}
    serve = d["spawn"]([sys.executable, "-m", "door", "serve", "start", "--port", str(port), "--web", str(d["web_dir"])],
                       log=logs / "serve.log", env=env)
    run = {"serve_pid": serve.pid, "port": port, "connection": connection,
           "started_at": datetime.now(UTC).isoformat(timespec="seconds")}
    local = f"http://127.0.0.1:{port}"
    if not _wait(lambda: d["answers"](local), tries=60, sleep=d["sleep"]):
        _stop_pids(run, d["kill"])
        return {"error": f"The other door's server did not start; see {logs / 'serve.log'}"}
    if d["platform"] == "darwin":  # a sleeping Mac cannot answer a phone
        run["awake_pid"] = d["spawn"](["caffeinate", "-i", "-w", str(serve.pid)], log=logs / "awake.log").pid

    if connection == "cloudflare":
        binary = d["find_cloudflared"]() or str(install_cloudflared())
        log = logs / "tunnel.log"
        if log.exists():
            log.unlink()
        run["tunnel_pid"] = d["spawn"]([binary, "tunnel", "--no-autoupdate", "--url", local], log=log).pid

        def address() -> str | None:
            text = log.read_text(errors="replace") if log.exists() else ""
            m = _TUNNEL_URL.search(text)
            return m.group(0) if m else None

        if not _wait(lambda: address() is not None, tries=120, sleep=d["sleep"]):
            _stop_pids(run, d["kill"])
            return {"error": f"the tunnel gave no address; see {log}"}
        # Ready when Cloudflare has registered the connection. The new name is not looked up from here:
        # a lookup before it exists is remembered as missing by this computer's resolver for a while.
        registered = lambda: "Registered tunnel connection" in log.read_text(errors="replace")  # noqa: E731
        if not _wait(registered, tries=120, sleep=d["sleep"]):
            _stop_pids(run, d["kill"])
            return {"error": f"the tunnel could not connect to Cloudflare; see {log}"}
        run["address"] = address()
    else:
        served = d["run"]([tailscale, "serve", "--bg", str(port)], capture_output=True, text=True)
        if served.returncode != 0:
            _stop_pids(run, d["kill"])
            said = (served.stdout or "") + (served.stderr or "")
            link = _LINK.search(said)
            if link:
                return {"needs": "enable_https", "link": link.group(0)}
            return {"error": f"tailscale serve failed: {said.strip()[:300]}"}
        run["address"] = f"https://{dns}"

    if connection == "tailscale":
        _wait(lambda: d["answers"](run["address"]), tries=60, sleep=d["sleep"])
    _write_run(home, run)
    return status(home, **deps)


def stop(home: Path, **deps) -> dict:
    """Stop what `start` started for this data folder."""
    d = {**_defaults(), **deps}
    run = _read_run(home)
    if not run:
        return {"stopped": False}
    _stop_pids(run, d["kill"])
    if run.get("connection") == "tailscale":
        tailscale = d["find_tailscale"]()
        if tailscale:
            d["run"]([tailscale, "serve", "--https=443", "off"], capture_output=True, text=True)
    _run_file(home).unlink(missing_ok=True)
    return {"stopped": True}


def _qr_svg(text: str) -> str:
    import segno

    # A whole document, not svg_inline's: the window shows it as an image, which needs the SVG namespace.
    out = io.BytesIO()
    segno.make(text, error="m").save(out, kind="svg", scale=6, border=2, xmldecl=False)
    return out.getvalue().decode("utf-8")


def pair(home: Path, device: str, **deps) -> dict:
    """A QR code that pairs one phone: ``{"device", "qr_svg", "expires_at"}``. The code is only inside the
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
