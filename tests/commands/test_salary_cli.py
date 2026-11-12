"""`./door jobs salary` and the `salary_estimate` MCP tool (#371)."""

import json

import pytest
from click.testing import CliRunner

import door.mcp_server as server
from cli_utils import write_list_posting
from door.cli import cli
from door.commands import find as find_cmd
from door.commands import prepare as prepare_cmd
from door.commands import salary as salary_cmd
from door.core import claude_cli, workspace
from profile_utils import write_config

ANSWER = {
    "found": True, "low": 55000, "high": 70000, "currency": "DKK", "period": "month", "gross": True,
    "position": "within", "basis": "ten years against the five asked",
    "sources": [{"title": "Stats", "url": "https://example.com/stats"}], "ad_salary": None,
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    profile, jobs = tmp_path / "profile", tmp_path / "jobs"
    write_config(profile, {})
    (profile / "cv.md").write_text("# Jane Doe\n\n## Work Experience\n\n### Controller | Acme — 2016 - present\n")
    write_list_posting(jobs, "2026-10-20", "jobindex", "jobindex.1", title="Senior Controller", company="Trustpilot",
                       description="Salary DKK 60,000 per month.")
    write_list_posting(jobs, "2026-10-20", "jobindex", "jobindex.2", title="Analyst", company="Novo")
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs)
    calls = []

    def fake_ask(system, text, **kw):
        calls.append({"system": system, "text": text, **kw})
        return dict(ANSWER)

    monkeypatch.setattr(claude_cli, "ask", fake_ask)
    return jobs, calls, profile


def test_asks_haiku_with_web_search_and_caches(env):
    jobs, calls, profile = env
    result = salary_cmd._salary_core("trustpilot", jobs_dir=jobs, profile_dir=profile)
    assert result["found"] and result["low"] == 55000 and result["job_id"] == "jobindex.1"
    assert result["cached"] is False
    assert calls[0]["model"] == "haiku" and calls[0]["allowed_tools"] == ("WebSearch",)
    cache = json.loads((jobs / "salary.json").read_text())
    assert cache["jobindex.1"]["high"] == 70000 and "as_of" in cache["jobindex.1"]


def test_second_look_makes_no_call_and_refresh_does(env):
    jobs, calls, profile = env
    salary_cmd._salary_core("trustpilot", jobs_dir=jobs, profile_dir=profile)
    again = salary_cmd._salary_core("trustpilot", jobs_dir=jobs, profile_dir=profile)
    assert len(calls) == 1 and again["cached"] is True and again["low"] == 55000
    salary_cmd._salary_core("trustpilot", refresh=True, jobs_dir=jobs, profile_dir=profile)
    assert len(calls) == 2


def test_no_source_means_no_number_and_nothing_cached(env, monkeypatch):
    jobs, calls, profile = env
    monkeypatch.setattr(claude_cli, "ask", lambda *a, **k: {"found": False})
    result = salary_cmd._salary_core("trustpilot", jobs_dir=jobs, profile_dir=profile)
    assert result["found"] is False and "low" not in result and "source" in result["message"]
    assert not (jobs / "salary.json").exists()


def test_failed_call_is_an_error_and_caches_nothing(env, monkeypatch):
    jobs, calls, profile = env

    def boom(*a, **k):
        raise claude_cli.ClaudeError("claude exited 1")

    monkeypatch.setattr(claude_cli, "ask", boom)
    with pytest.raises(claude_cli.ClaudeError):
        salary_cmd._salary_core("trustpilot", jobs_dir=jobs, profile_dir=profile)
    assert not (jobs / "salary.json").exists()


def test_cli_prints_range_position_and_sources(env):
    result = CliRunner().invoke(cli, ["jobs", "salary", "trustpilot"])
    assert result.exit_code == 0, result.output
    assert "55,000" in result.output and "DKK" in result.output and "https://example.com/stats" in result.output
    assert "estimate" in result.output.lower()


def test_cli_says_plainly_when_nothing_is_cited(env, monkeypatch):
    monkeypatch.setattr(claude_cli, "ask", lambda *a, **k: None)
    result = CliRunner().invoke(cli, ["jobs", "salary", "trustpilot"])
    assert result.exit_code == 0 and "no salary source" in result.output.lower()


def test_tool_matches_the_core_and_reports_errors(env):
    assert server.salary_estimate("trustpilot")["low"] == 55000
    assert "error" in server.salary_estimate("nosuchjob")


def test_find_never_asks_for_a_salary():
    import inspect

    assert "salary" not in inspect.getsource(find_cmd)


def _age(jobs, job_id, days):
    from datetime import datetime, timedelta, timezone

    store = json.loads((jobs / "salary.json").read_text())
    store[job_id]["as_of"] = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    (jobs / "salary.json").write_text(json.dumps(store))


def test_max_age_reuses_a_fresh_estimate_and_asks_again_for_an_old_one(env):
    jobs, calls, profile = env
    salary_cmd._salary_core("trustpilot", jobs_dir=jobs, profile_dir=profile)
    _age(jobs, "jobindex.1", salary_cmd.STALE_AFTER_DAYS - 1)
    again = salary_cmd._salary_core("trustpilot", max_age_days=salary_cmd.STALE_AFTER_DAYS, jobs_dir=jobs, profile_dir=profile)
    assert len(calls) == 1 and again["cached"] is True
    _age(jobs, "jobindex.1", salary_cmd.STALE_AFTER_DAYS + 1)
    salary_cmd._salary_core("trustpilot", jobs_dir=jobs, profile_dir=profile)
    assert len(calls) == 1  # asked by the user: an old estimate is still shown, `refresh` asks anew
    renewed = salary_cmd._salary_core("trustpilot", max_age_days=salary_cmd.STALE_AFTER_DAYS, jobs_dir=jobs, profile_dir=profile)
    assert len(calls) == 2 and renewed["cached"] is False


@pytest.fixture
def prepared(env, monkeypatch):
    from cli_utils import fake_tailor

    jobs, calls, profile = env
    monkeypatch.setattr(prepare_cmd, "_run_tailor", fake_tailor(jobs))
    return jobs, calls, profile


def test_prepare_estimates_the_salary_once_and_shows_it(prepared):
    jobs, calls, profile = prepared
    result = prepare_cmd._prepare_core("jobindex.1", jobs_dir=jobs, profile_dir=profile)
    assert result["outcome"] == "prepared"
    assert result["salary"]["low"] == 55000 and len(calls) == 1
    # the tailor is never handed the estimate: it is only shown
    assert not any("55000" in str(c) for c in calls[1:])
    again = prepare_cmd._prepare_core("jobindex.1", force=True, jobs_dir=jobs, profile_dir=profile)
    assert again["salary"]["cached"] is True and len(calls) == 1


def test_prepare_refreshes_a_stale_estimate(prepared):
    jobs, calls, profile = prepared
    prepare_cmd._prepare_core("jobindex.1", jobs_dir=jobs, profile_dir=profile)
    _age(jobs, "jobindex.1", salary_cmd.STALE_AFTER_DAYS + 1)
    prepare_cmd._prepare_core("jobindex.1", force=True, jobs_dir=jobs, profile_dir=profile)
    assert len(calls) == 2


def test_prepare_says_nothing_when_no_source_is_found(prepared, monkeypatch):
    jobs, calls, profile = prepared
    monkeypatch.setattr(claude_cli, "ask", lambda *a, **k: {"found": False})
    result = prepare_cmd._prepare_core("jobindex.1", jobs_dir=jobs, profile_dir=profile)
    assert result["outcome"] == "prepared" and result["salary"] is None


def test_a_failed_estimate_never_fails_prepare(prepared, monkeypatch):
    jobs, calls, profile = prepared

    def boom(*a, **k):
        raise claude_cli.ClaudeError("claude exited 1")

    monkeypatch.setattr(claude_cli, "ask", boom)
    result = prepare_cmd._prepare_core("jobindex.1", jobs_dir=jobs, profile_dir=profile)
    assert result["outcome"] == "prepared" and result["salary"] is None


@pytest.mark.parametrize("status", ["allowed_warning", "rejected"])
def test_prepare_skips_the_estimate_when_the_plan_is_nearly_full(prepared, monkeypatch, status):
    from door.core import usage

    jobs, calls, profile = prepared
    monkeypatch.setattr(usage, "room", lambda *a, **k: {"as_of": "2026-11-07T10:00:00+00:00", "status": status})
    result = prepare_cmd._prepare_core("jobindex.1", jobs_dir=jobs, profile_dir=profile)
    assert result["outcome"] == "prepared" and result["salary"] is None and calls == []


def test_a_failed_prepare_asks_for_no_salary(prepared, monkeypatch):
    jobs, calls, profile = prepared

    def failing(job_id, posting_path, **kw):
        raise prepare_cmd.TailorError("boom")

    monkeypatch.setattr(prepare_cmd, "_run_tailor", failing)
    result = prepare_cmd._prepare_core("jobindex.1", jobs_dir=jobs, profile_dir=profile)
    assert result["outcome"] == "failed" and calls == []


def test_show_carries_the_cached_salary_and_never_asks(env):
    from door.commands import matches as matches_cmd

    jobs, calls, profile = env
    assert matches_cmd._show_core("jobindex.1", jobs_dir=jobs)["salary"] is None
    salary_cmd._salary_core("trustpilot", jobs_dir=jobs, profile_dir=profile)
    shown = matches_cmd._show_core("jobindex.1", jobs_dir=jobs)
    assert shown["salary"]["low"] == 55000 and shown["salary"]["sources"][0]["url"] == "https://example.com/stats"
    assert len(calls) == 1


def test_jobs_show_prints_the_cached_salary(env):
    jobs, calls, profile = env
    salary_cmd._salary_core("trustpilot", jobs_dir=jobs, profile_dir=profile)
    result = CliRunner().invoke(cli, ["jobs", "show", "trustpilot"])
    assert result.exit_code == 0, result.output
    assert "55,000–70,000 DKK per month" in result.output
