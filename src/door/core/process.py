"""Processes that outlive the call that started them, and the run.json they leave (the phone server, #444; the PDF
printer's browser): start one in a session of its own, ask whether it lives, end it with everything it started, and
read and write its run state."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from door.core import utils, workspace


def spawn_detached(argv: list[str], *, log: Path, env: dict | None = None):
    """Start `argv` as a process of its own. On Windows a server has no console (DETACHED_PROCESS)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    out = open(log, "ab")  # noqa: SIM115 - handed to the child, which outlives this call
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    extra = {"creationflags": 0x00000008 | 0x00000200} if sys.platform == "win32" else {"start_new_session": True}
    return subprocess.Popen(argv, stdout=out, stderr=out, stdin=subprocess.DEVNULL, env=env, **extra)


def door_env(home: Path) -> dict:
    """The environment of a `python -m door` started for the data folder `home`, on this checkout's source."""
    return {**os.environ, "DOOR_HOME": str(home), "PYTHONPATH": str(workspace.REPO_ROOT / "src")}


def is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def kill_tree(pid: int, sig: int = signal.SIGTERM, *, group: bool = False) -> None:
    """End a process this module started, with everything it started: each runs in a session of its own
    (`spawn_detached`), and Python on a Mac starts the real server as a child of a launcher. With `group` the pid
    is known to be a session leader's (its id is the group's, still true after the leader was reaped), and the group
    is signalled whatever became of the leader; otherwise a pid that leads no group is ended alone: the group is
    somebody else's. On Windows the whole tree is always ended (taskkill), `sig` and `group` unused."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, timeout=15, stdin=subprocess.DEVNULL)
        elif group or os.getpgid(pid) == pid:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)
    except (OSError, subprocess.SubprocessError):
        pass


def read_run(path: Path) -> dict | None:
    """The run state at `path`; None when it is missing or unreadable."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_run(path: Path, run: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    utils.write_json_atomic(path, run)
