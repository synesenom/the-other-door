"""Shared by the CLI journeys (tests/cli_journeys/): CLI journeys (#33, layer 2): the real `./door` (`door.cmd` on Windows) in the app's test world.

Not in the default offline suite (marker `cli_journeys`): CI runs them on Linux and Windows after
`setup.sh` / `setup.ps1` on a fresh checkout (.github/workflows/cli-journeys.yml), and
`./scripts/run-test.sh --cli-journeys` runs them here. The world is built by `app/test/world/make-world.ts`
(needs Node and `npm ci` in `app/`); `DOOR_PYTHON` names the Poetry interpreter its stand-in `claude` and
`tectonic` run on. The world's edges reach the CLI through the test-only hook `app/test/world/hook`
(`sitecustomize`, `python -m door` inside a world only) and `init`'s prompts are scripted (`prompts.json`).
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from paths import REPO_ROOT

APP = REPO_ROOT / "app"
IS_WINDOWS = sys.platform == "win32"


def _skip_reason() -> str | None:
    if not shutil.which("npx"):
        return "npx is not installed (Node 22)"
    if not shutil.which("poetry"):
        return "poetry is not on PATH"
    if not os.environ.get("DOOR_PYTHON"):
        return "DOOR_PYTHON is not set (the Poetry interpreter: poetry run python -c 'import sys;print(sys.executable)')"
    if not (APP / "node_modules" / ".bin" / ("tsx.cmd" if IS_WINDOWS else "tsx")).exists():
        return "the app's packages are not installed (npm ci in app/)"
    return None


class World:
    """A built test world and the real CLI run inside it."""

    def __init__(self, info: dict):
        self.info = info
        self.home = Path(info["home"])
        self.dir = Path(info["dir"])
        self.jobs = info["jobs"]
        self.persona = info["persona"]
        self.env = {
            **os.environ,
            "DOOR_HOME": info["home"],
            "DOOR_WORLD": info["dir"],
            "LANG": "en_US.UTF-8",
            "TZ": "Europe/Copenhagen",
            "PYTHONUTF8": "1",
            "DOOR_WORLD_CLOCK": "continuous",
            "PYTHONPATH": info["hook"],
            "PATH": info["bin"] + os.pathsep + os.environ.get("PATH", ""),
        }

    def script_prompts(self, answers: dict) -> None:
        (self.dir / "prompts.json").write_text(json.dumps(answers), encoding="utf-8")

    def door(self, *args: str, timeout: int = 600) -> tuple[int, str, str]:
        launcher = str(REPO_ROOT / ("door.cmd" if IS_WINDOWS else "door"))
        done = subprocess.run([launcher, *args], cwd=REPO_ROOT, env=self.env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
        return done.returncode, done.stdout, done.stderr

    def set_board(self, site: str, **fields) -> None:
        """Change what the world's board `site` does (`fail="msg"`); read again by every scrape."""
        path = self.dir / "world.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("boards", {}).setdefault(site, {}).update(fields)
        path.write_text(json.dumps(data), encoding="utf-8")

    def clear_board_fault(self, site: str) -> None:
        path = self.dir / "world.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.get("boards", {}).get(site, {}).pop("fail", None)
        path.write_text(json.dumps(data), encoding="utf-8")

    def faults(self, faults: dict) -> None:
        """Make the stand-in `claude` fail as `faults` says (`{"claude": {"tailor": {"fail": "msg"}}}`); `{}` clears."""
        (self.dir / "faults.json").write_text(json.dumps(faults), encoding="utf-8")

    def calls(self) -> list[dict]:
        path = self.dir / "calls.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line] if path.exists() else []

    def claude_kinds(self) -> list[str]:
        return [c["call"] for c in self.calls() if c.get("kind") == "claude"]

    def read(self, relative: str):
        return json.loads((self.home / relative).read_text(encoding="utf-8"))


def build_world(persona: str = "mette", empty: bool = False) -> World:
    if reason := _skip_reason():
        # In CI (or where the journeys are required: the workflow, `run-test.sh --cli-journeys|--release`) a skip would pass unseen.
        if os.environ.get("CI") or os.environ.get("DOOR_CLI_JOURNEYS_REQUIRED") == "1":
            pytest.fail(f"the CLI journeys cannot run here: {reason}", pytrace=False)
        pytest.skip(reason)
    cmd = ["npx", "tsx", "test/world/make-world.ts", persona, *(["--empty"] if empty else [])]
    out = subprocess.run(cmd, cwd=APP, capture_output=True, text=True, check=True, shell=IS_WINDOWS, encoding="utf-8")
    return World(json.loads(out.stdout))
