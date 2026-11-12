"""Keeping a person's `door serve` running on a Mac (#302): a launchd agent per instance, started at
login and restarted when it stops. `serve install-agent` writes and loads it, `serve uninstall-agent`
unloads and removes it."""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path

AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "door"


def label(name: str) -> str:
    return f"dev.door.serve.{_slug(name)}"


def plist(*, home: Path, port: int, name: str, python: str, src: str, path: str) -> dict:
    home = Path(home)
    log = str(home / "logs" / "serve.log")
    return {
        "Label": label(name),
        "ProgramArguments": [python, "-m", "door", "serve", "start", "--port", str(port), "--name", name],
        "EnvironmentVariables": {"DOOR_HOME": str(home), "PYTHONPATH": src, "PATH": path},
        "WorkingDirectory": str(Path(src).parent),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


def install(*, home: Path, port: int, name: str, agents_dir: Path = AGENTS_DIR, platform: str = sys.platform,
            run=subprocess.run, uid: int | None = None) -> Path:
    """Write this instance's agent and load it; the path of the plist."""
    if platform != "darwin":
        raise ValueError("a launch agent is for macOS; elsewhere start `serve` with your system's service manager")
    from door.core import workspace

    (Path(home) / "logs").mkdir(parents=True, exist_ok=True)
    data = plist(home=home, port=port, name=name, python=sys.executable, src=str(workspace.REPO_ROOT / "src"),
                 path=os.pathsep.join([str(Path.home() / ".local" / "bin"), os.environ.get("PATH", "/usr/bin:/bin")]))
    agents_dir = Path(agents_dir)
    agents_dir.mkdir(parents=True, exist_ok=True)
    target = agents_dir / f"{data['Label']}.plist"
    domain = f"gui/{os.getuid() if uid is None else uid}"
    if target.exists():  # a new version replaces the running one
        run(["launchctl", "bootout", domain, str(target)], check=False, capture_output=True)
    target.write_bytes(plistlib.dumps(data))
    run(["launchctl", "bootstrap", domain, str(target)], check=False, capture_output=True)
    return target


def uninstall(*, name: str, agents_dir: Path = AGENTS_DIR, platform: str = sys.platform, run=subprocess.run,
              uid: int | None = None) -> Path | None:
    """Unload and remove the agent; its former path, or None when there was none."""
    if platform != "darwin":
        raise ValueError("a launch agent is for macOS")
    target = Path(agents_dir) / f"{label(name)}.plist"
    if not target.exists():
        return None
    run(["launchctl", "bootout", f"gui/{os.getuid() if uid is None else uid}", str(target)], check=False, capture_output=True)
    target.unlink()
    return target
