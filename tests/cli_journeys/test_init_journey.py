"""`door init` and the first `find` it starts, the real process on a fresh data folder (#33)."""

import json
from pathlib import Path

import pytest

from cli_world import build_world
from paths import REPO_ROOT


@pytest.fixture(scope="module")
def world():
    return build_world("mette", empty=True)


def test_init_then_the_first_find(world):
    world.script_prompts({"cv_sources": {"answer": world.info["cvFile"]}})
    code, out, err = world.door("init")
    assert code == 0, f"{out}\n{err}"
    assert f"Wrote {Path('profile/config.json')}." in out
    assert "[1/5] search" in out and "[5/5] match" in out, out   # the first run it starts

    config = world.read("profile/config.json")
    assert config["name"] == world.persona["name"]
    assert config["email"] == world.persona["email"]
    cv = (world.home / "profile" / "cv.md").read_text(encoding="utf-8")
    assert cv.strip()
    assert cv != (REPO_ROOT / "profile.example" / "cv.md").read_text(encoding="utf-8")

    kinds = world.claude_kinds()
    positions = [kinds.index(k) for k in ("draft", "basics", "titles", "keywords")]
    assert positions == sorted(positions), kinds
    prompts = [c["name"] for c in world.calls() if c["kind"] == "prompt"]
    assert prompts.index("review") > prompts.index("titles_pick")

    assert list((world.home / "jobs" / "postings").glob("*/*/*.json")), out
    assert list((world.home / "jobs" / "runs").glob("*.json"))


def test_init_by_flags_asks_nothing(world):
    before = len(world.calls())
    code, out, err = world.door("init", "--name", "Mette Test", "--email", "m@example.com", "--set", "min_score=0.5")
    assert code == 0, f"{out}\n{err}"
    assert world.read("profile/config.json")["min_score"] == 0.5
    assert not [c for c in world.calls()[before:] if c["kind"] == "prompt"]
