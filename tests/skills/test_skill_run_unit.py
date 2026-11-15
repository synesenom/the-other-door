"""The skill runner's pure helpers (offline): when a run stops, and who the stand-in user is."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("claude_agent_sdk")
sys.path.insert(0, str(Path(__file__).parent))

import skill_run  # noqa: E402


def test_a_run_finishes_once_the_stop_tool_was_called():
    assert not skill_run.finished("find_jobs", ["doctor", "init_profile"])
    assert skill_run.finished("find_jobs", ["doctor", "find_jobs"])
    assert skill_run.finished("mark_reviewed", ["status_summary", "mark_reviewed"])


def test_the_onboarded_user_is_not_setting_up_and_the_facts_note_is_added():
    onboarding = skill_run.user_rules("onboarding")
    onboarded = skill_run.user_rules("onboarded", "You want none of the proposals.")
    assert "setting up" in onboarding
    assert "setting up" not in onboarded
    assert "I'm done" in onboarded
    assert "You want none of the proposals." in onboarded
