"""`./door market` and the `market` MCP tool."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner

from door.cli import cli
from door.core import claude_cli, workspace
from cli_utils import write_list_posting
from profile_utils import write_config


@pytest.fixture
def env(tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise claude_cli.ClaudeError("claude is not available in tests")

    monkeypatch.setattr(claude_cli, "ask", refuse)
    profile, jobs = tmp_path / "profile", tmp_path / "jobs"
    write_config(profile, {"role_targets": ["Data Engineer"], "min_score": 0.5})
    when = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    write_list_posting(jobs, "2026-10-20", "jobindex", "a", posted_at=when, score=0.8, score_reason="ok", scored_by="haiku",
                       matching_skills=["Python"], missing_skills=["dbt"])
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs)
    return jobs


def test_market_prints_report_and_saves(env):
    result = CliRunner().invoke(cli, ["market"])
    assert result.exit_code == 0, result.output
    assert "Market" in result.output and "Python" in result.output
    assert len(list((env / "market").glob("report-*.md"))) == 1


def test_market_days_option(env):
    result = CliRunner().invoke(cli, ["market", "--days", "7", "--no-save"])
    assert result.exit_code == 0 and "last 7 days" in result.output


def test_scored_companies_flag(env):
    result = CliRunner().invoke(cli, ["market", "--scored-companies", "--no-save"])
    assert result.exit_code == 0 and "scored ads" in result.output


def test_market_no_save_flag(env):
    CliRunner().invoke(cli, ["market", "--no-save"])
    assert not (env / "market").exists()


def test_market_invalid_days_exits_nonzero(env):
    result = CliRunner().invoke(cli, ["market", "--days", "0"])
    assert result.exit_code == 1 and "Error" in result.output


def test_market_makes_no_call_when_every_name_is_known(env, monkeypatch):
    (env / "skill_aliases.json").write_text(json.dumps({"python": "Python", "dbt": "dbt"}), encoding="utf-8")

    def boom(*a, **k):
        raise AssertionError("no claude")

    monkeypatch.setattr(claude_cli, "run", boom)
    monkeypatch.setattr(claude_cli, "ask", boom)
    assert CliRunner().invoke(cli, ["market"]).exit_code == 0


def test_market_cli_prints_warning_on_failed_call(env, monkeypatch):
    def fail(*a, **k):
        raise claude_cli.ClaudeError("down")

    monkeypatch.setattr(claude_cli, "ask", fail)
    result = CliRunner().invoke(cli, ["market"])
    assert result.exit_code == 0 and "Warning:" in result.output


