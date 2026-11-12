"""The `door serve` instances on this machine (#302): one per person, each its own data folder, port and
Claude plan. `serve start` registers its home here (`instances.json` in the per-user config folder,
beside `drive.json`) and is refused when it would share a port or a plan with another person's; `doctor`
lists them."""

from __future__ import annotations

import json
import os
from pathlib import Path

from door.core import drive


def _path() -> Path:
    return drive._base() / "instances.json"


def read() -> dict[str, dict]:
    """``{home: {"port", "name", "claude_config_dir"}}``; empty when none is registered."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _plan(claude_config_dir: str | None) -> str:
    return str(Path(claude_config_dir).expanduser().resolve()) if claude_config_dir else "the default Claude login"


def register(home: Path, *, port: int, name: str, claude_config_dir: str | None) -> None:
    """Record this home's instance; ValueError when another person's uses the same port or Claude plan."""
    key = str(Path(home).resolve())
    data = read()
    for other, entry in data.items():
        if other == key:
            continue
        if entry.get("port") == port:
            raise ValueError(f"port {port} is {entry.get('name') or other}'s; give this one another --port")
        if _plan(entry.get("claude_config_dir")) == _plan(claude_config_dir):
            raise ValueError(
                f"{entry.get('name') or other} already uses {_plan(claude_config_dir)}: each person needs their own Claude plan. "
                "Set claude_config_dir in this profile's config.json to a folder of its own and sign in there "
                "(CLAUDE_CONFIG_DIR=<that folder> claude auth login)"
            )
    data[key] = {"port": port, "name": name, "claude_config_dir": claude_config_dir}
    _write(data)


def unregister(home: Path) -> None:
    data = read()
    if data.pop(str(Path(home).resolve()), None) is not None:
        _write(data)
