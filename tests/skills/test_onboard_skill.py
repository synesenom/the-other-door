"""/onboard, run by the real model on the local plan against the app's test world (#33).

Not in the offline suite or CI (marker `skills`): `./scripts/run-test.sh --skills`, before a release. The
conversation is real; the server is the test world's (boot.py), its own model calls the stand-in claude;
the user is a small model playing the persona (`skill_run.py`). Every check is on behaviour: which tools,
in which order, what was written and when, never on the model's wording.
"""

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from paths import REPO_ROOT

pytestmark = pytest.mark.skills

APP = REPO_ROOT / "app"
DISCOVERY_KEYS = ("linkedin_discovery", "profession_discovery", "jobbsafari_discovery", "hellowork_discovery")


def _ready() -> str | None:
    """Why the skill run cannot happen here, or None."""
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return "claude-agent-sdk is not installed (poetry install)"
    if not shutil.which("claude"):
        return "no claude on PATH"
    if not (APP / "node_modules" / ".bin" / "tsx").exists():
        return "the app's packages are not installed (npm ci in app/)"
    status = subprocess.run(["claude", "auth", "status", "--json"], capture_output=True, text=True)
    if status.returncode != 0 or not json.loads(status.stdout or "{}").get("loggedIn"):
        return "claude is not signed in (claude auth login)"
    return None


@pytest.fixture(scope="module")
def onboarded(tmp_path_factory):
    """One /onboard of mette, start to finish: the world, the run's result, its transcript folder."""
    if reason := _ready():
        pytest.skip(reason)
    sys.path.insert(0, str(Path(__file__).parent))
    import skill_run

    out = subprocess.run(["npx", "tsx", "test/world/make-world.ts", "mette", "--empty"], cwd=APP,
                         capture_output=True, text=True, check=True)
    world = json.loads(out.stdout)
    folder = tmp_path_factory.mktemp("onboard")
    result = asyncio.run(skill_run.run(world, "/onboard", "sonnet", 12, folder))
    print(f"\n/onboard transcript: {folder / 'transcript.md'}")
    return world, result


def _home(world) -> Path:
    return Path(world["home"])


def _order(result) -> list[str]:
    return result["tools"]


def test_it_reads_the_sources_through_the_tools_before_anything_else(onboarded):
    _, result = onboarded
    tools = _order(result)
    assert "draft_cv" in tools and "infer_basics" in tools, tools
    assert tools.index("draft_cv") < tools.index("infer_basics") < tools.index("init_profile"), tools


def test_it_never_reads_a_source_itself_nor_runs_a_shell_command(onboarded):
    world, result = onboarded
    source = Path(world["cvFile"]).resolve()
    misused = [u for u in result["used"]
               if u["tool"] in ("Bash", "Write")
               or (u["tool"] == "Read" and Path(u["input"].get("file_path", "")).resolve() == source)]
    assert not misused, misused


def test_it_writes_the_profile_only_after_the_confirmation_then_starts_the_first_run(onboarded):
    world, result = onboarded
    tools = _order(result)
    assert tools.count("init_profile") == 1, tools
    assert tools.index("init_profile") < tools.index("save_cv") < tools.index("find_jobs"), tools
    init_at = next(c["at"] for c in result["calls"] if c["tool"] == "init_profile")
    config = _home(world) / "profile" / "config.json"
    assert config.stat().st_mtime >= init_at - 1
    assert next(c for c in reversed(result["calls"]) if c["tool"] == "find_jobs")["args"].get("skip") == [
        "discover", "follow", "collect"]


def test_the_saved_profile_is_the_persona(onboarded):
    world, _ = onboarded
    persona = world["persona"]
    config = json.loads((_home(world) / "profile" / "config.json").read_text(encoding="utf-8"))
    assert (config["name"], config["email"], config["location"]) == (persona["name"], persona["email"], persona["city"])
    assert sorted(config["languages"]) == sorted(persona["languages"])
    assert persona["roleTargets"][0] in config["role_targets"]
    assert set(config["role_targets"]) <= set(persona["roleTargets"]), config["role_targets"]
    # Asked about (LinkedIn serves Copenhagen) and left off; none turned on.
    assert config.get("linkedin_discovery") is False
    assert not any(config.get(key) for key in DISCOVERY_KEYS), {k: config.get(k) for k in DISCOVERY_KEYS}


def test_the_saved_cv_is_the_confirmed_draft(onboarded):
    world, _ = onboarded
    profile = _home(world) / "profile"
    assert " ".join((profile / "cv.md").read_text(encoding="utf-8").split()) == " ".join(world["persona"]["cv"].split())
    assert not (profile / "cv.draft.md").exists()
