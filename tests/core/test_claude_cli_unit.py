"""Every `claude` subprocess runs against the plan named by `claude_config_dir`.

A shell alias such as `claude-personal` (`CLAUDE_CONFIG_DIR=~/.claude-personal claude`)
does not exist for a subprocess, so door sets `CLAUDE_CONFIG_DIR` itself from
profile/config.json — the same plan from a conversation, a terminal or cron.
"""

import json
import subprocess
import types
from pathlib import Path

import pytest

from door.commands import prepare as prepare_cmd
from door.core import claude_cli, doctor, profile_loader, scraper_fix, workspace
from door.matching import scorer
from door.matching.language import _run_claude as real_language_run_claude  # conftest stubs the attribute


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """A profile dir whose config.json sets claude_config_dir; returns a setter."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)

    def write(value):
        cfg = {} if value is None else {"claude_config_dir": value}
        (profile_dir / "config.json").write_text(json.dumps(cfg))
        return profile_dir

    return write


def test_env_sets_the_configured_dir_expanded(profile, monkeypatch):
    monkeypatch.setenv("HOME", "/home/me")
    profile("~/.claude-personal")
    assert claude_cli.env({})["CLAUDE_CONFIG_DIR"] == str(Path("/home/me/.claude-personal"))


def test_configured_dir_wins_over_the_inherited_one(profile):
    profile("/plans/personal")
    env = claude_cli.env({"CLAUDE_CONFIG_DIR": "/plans/company", "PATH": "/bin"})
    assert env == {"CLAUDE_CONFIG_DIR": "/plans/personal", "PATH": "/bin"}


def test_unset_key_leaves_the_environment_alone(profile):
    profile(None)
    assert claude_cli.env({"CLAUDE_CONFIG_DIR": "/inherited"}) == {"CLAUDE_CONFIG_DIR": "/inherited"}


def test_missing_or_broken_config_leaves_the_environment_alone(profile):
    profile_dir = profile(None)
    (profile_dir / "config.json").unlink()
    assert claude_cli.env({"A": "1"}) == {"A": "1"}
    (profile_dir / "config.json").write_text("{not json")
    assert claude_cli.env({"A": "1"}) == {"A": "1"}


def test_env_does_not_mutate_its_base(profile):
    profile("/plans/personal")
    base = {"A": "1"}
    claude_cli.env(base)
    assert base == {"A": "1"}


def test_env_defaults_to_the_process_environment(profile, monkeypatch):
    profile("/plans/personal")
    monkeypatch.setenv("SOME_VAR", "x")
    env = claude_cli.env()
    assert env["SOME_VAR"] == "x" and env["CLAUDE_CONFIG_DIR"] == "/plans/personal"


def test_profile_accepts_the_key():
    assert "claude_config_dir" in profile_loader.Profile.model_fields


# --------------------------------------------------------------------------- #
# every call site
# --------------------------------------------------------------------------- #

def _capture(calls, stdout=""):
    def run(argv, **kwargs):
        calls.append(kwargs.get("env"))
        return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    return run


def test_scoring_uses_the_configured_plan(profile):
    profile("/plans/personal")
    calls = []
    scorer._score_chunk(
        [{"id": "a"}], system_prompt="s", model="haiku", fallback_model=None, max_retries=0,
        base_backoff=0, max_backoff=0, sleep_fn=lambda s: None, run_fn=_capture(calls),
    )
    assert calls and calls[0]["CLAUDE_CONFIG_DIR"] == "/plans/personal"


def test_title_translation_uses_the_configured_plan(profile):
    profile("/plans/personal")
    calls = []
    real_language_run_claude(["claude", "-p"], "x", which=lambda name: "/bin/claude", run=_capture(calls))
    assert calls[0]["CLAUDE_CONFIG_DIR"] == "/plans/personal"


@pytest.mark.parametrize("call", ["tailor", "scraper_fixer"])
def test_agent_runs_use_the_configured_plan(profile, monkeypatch, tmp_path, call):
    profile("/plans/personal")
    calls = []
    monkeypatch.setattr(subprocess, "run", _capture(calls))
    if call == "tailor":
        prepare_cmd._run_tailor("job", tmp_path / "posting.json")
    else:
        scraper_fix._run_scraper_fixer("jobindex", tmp_path / "raw.html")
    assert calls[0]["CLAUDE_CONFIG_DIR"] == "/plans/personal"


def test_login_check_asks_the_configured_plan(profile):
    profile("/plans/personal")
    calls = []

    def run(argv, **kwargs):
        calls.append(kwargs.get("env"))
        return types.SimpleNamespace(returncode=0, stdout=json.dumps({"loggedIn": True, "authMethod": "claude.ai"}), stderr="")

    check = doctor.check_claude_login("/bin/claude", run=run, env=claude_cli.env({}))
    assert calls[0]["CLAUDE_CONFIG_DIR"] == "/plans/personal"
    assert "/plans/personal" in check["detail"]
