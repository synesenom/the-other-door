"""Shared pieces of the skill journeys (#33): is a real run possible here, the test world, one run."""

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from paths import REPO_ROOT

sys.path.insert(0, str(Path(__file__).parent))

APP = REPO_ROOT / "app"


def claude_ready() -> str | None:
    """Why the real model cannot run here (no signed-in claude), or None."""
    if not shutil.which("claude"):
        return "no claude on PATH"
    status = subprocess.run(["claude", "auth", "status", "--json"], capture_output=True, text=True)
    if status.returncode != 0 or not json.loads(status.stdout or "{}").get("loggedIn"):
        return "claude is not signed in (claude auth login)"
    return None


def ready() -> str | None:
    """Why the skill run cannot happen here, or None."""
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return "claude-agent-sdk is not installed (poetry install)"
    if not (APP / "node_modules" / ".bin" / "tsx").exists():
        return "the app's packages are not installed (npm ci in app/)"
    return claude_ready()


def make_world(*flags: str) -> dict:
    """A fresh test world for mette (`--empty` for none of her data yet)."""
    out = subprocess.run(["npx", "tsx", "test/world/make-world.ts", "mette", *flags], cwd=APP,
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def run_skill(tmp_path_factory, name: str, prompt: str, *, empty: bool = False, max_turns: int = 12, seed=None,
              **options):
    """One run of `prompt` in a new world: (world, result). `seed(world)` changes the world before the run.
    Skips the module when a real run is not possible."""
    if reason := ready():
        pytest.skip(reason)
    import skill_run

    world = make_world(*(["--empty"] if empty else []))
    if seed:
        seed(world)
    folder = tmp_path_factory.mktemp(name)
    cv = home(world) / "profile" / "cv.md"
    before = cv.read_bytes() if cv.exists() else None
    result = asyncio.run(skill_run.run(world, prompt, "sonnet", max_turns, folder, **options))
    result["cv_before"] = before   # the CV's bytes as the world made it, for a run that must not touch it
    print(f"\n{name} transcript: {folder / 'transcript.md'}")
    return world, result


def home(world) -> Path:
    return Path(world["home"])
