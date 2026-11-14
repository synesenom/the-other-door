"""The upgrade runs when the CLI and the MCP server start, and a failed or newer data folder stops every command but the
ones that let the user report it (#56)."""

import asyncio
import json

import pytest
from click.testing import CliRunner

from door import mcp_server
from door.cli import cli
from door.core import migrations

FAILED = {"state": "failed", "message": migrations.FAILED.format(step="the step")}
NEWER = {"state": "newer", "message": migrations.NEWER}


def _answer(result):
    return json.loads(result[0].text)


@pytest.fixture
def started(monkeypatch):
    """Count the start-up upgrades (the autouse fixture turned the real one off)."""
    calls = []
    monkeypatch.setattr(migrations, "run_at_start", lambda: calls.append(1))
    return calls


# ---- the CLI --------------------------------------------------------------------------------------------


def test_a_command_upgrades_the_data_first(started, cli_env):
    CliRunner().invoke(cli, ["jobs"])
    assert started == [1]


def test_help_does_not_upgrade_anything(started):
    CliRunner().invoke(cli, ["--help"])
    CliRunner().invoke(cli, ["jobs", "--help"])
    CliRunner().invoke(cli, [])
    assert started == []


@pytest.mark.parametrize("state", [FAILED, NEWER])
def test_a_refused_data_folder_stops_a_command_with_the_line(monkeypatch, state, cli_env):
    monkeypatch.setattr(migrations, "_state", state)
    result = CliRunner().invoke(cli, ["jobs"])
    assert result.exit_code == 1
    assert state["message"] in result.output


@pytest.mark.parametrize("args", [["doctor"], ["data", "report", "--help"]])
def test_doctor_and_report_still_run(monkeypatch, args, cli_env):
    monkeypatch.setattr(migrations, "_state", FAILED)
    result = CliRunner().invoke(cli, args)
    assert FAILED["message"] not in result.output


# ---- the MCP server -------------------------------------------------------------------------------------


@pytest.mark.parametrize("state", [FAILED, NEWER])
def test_every_tool_but_report_and_doctor_answers_the_error(monkeypatch, state):
    monkeypatch.setattr(migrations, "_state", state)
    answer = _answer(asyncio.run(mcp_server.mcp.call_tool("list_stories", {})))
    assert answer == {"error": state["message"]}


def test_the_refusal_is_not_logged_on_every_call(monkeypatch):
    lines = []
    monkeypatch.setattr(mcp_server.problem_log, "failure", lambda where, message: lines.append(message))
    monkeypatch.setattr(migrations, "_state", FAILED)
    for _ in range(3):
        asyncio.run(mcp_server.mcp.call_tool("list_stories", {}))
    assert lines == []


def test_report_problem_and_doctor_are_not_gated(monkeypatch):
    monkeypatch.setattr(migrations, "_state", FAILED)
    assert mcp_server._data_refusal("report_problem") is None
    assert mcp_server._data_refusal("doctor") is None
    assert mcp_server._data_refusal("list_matches") == FAILED["message"]


def test_a_busy_state_is_retried_on_the_next_call(monkeypatch):
    monkeypatch.setattr(migrations, "_state", {"state": "busy", "message": "a run is in progress"})
    monkeypatch.setattr(migrations, "upgrade_all", lambda *a, **k: migrations._set(None))
    answer = _answer(asyncio.run(mcp_server.mcp.call_tool("list_stories", {})))
    assert "error" not in answer


def test_a_busy_state_that_stays_busy_answers_the_holders_message(monkeypatch):
    busy = {"state": "busy", "message": "a run is in progress; try again when it has finished"}
    monkeypatch.setattr(migrations, "_state", busy)
    monkeypatch.setattr(migrations, "upgrade_all", lambda *a, **k: migrations._set(busy))
    assert _answer(asyncio.run(mcp_server.mcp.call_tool("list_stories", {}))) == {"error": busy["message"]}


def test_main_upgrades_before_it_pulls_and_skips_the_pull_when_refused(monkeypatch):
    order = []
    monkeypatch.setattr(mcp_server.problem_log, "setup", lambda: order.append("log"))
    monkeypatch.setattr(migrations, "run_at_start", lambda: order.append("upgrade"))
    monkeypatch.setattr(mcp_server.i18n, "preload_language_detection", lambda: order.append("preload"))
    monkeypatch.setattr(mcp_server, "_startup_pull", lambda: order.append("pull"))
    monkeypatch.setattr(mcp_server.mcp, "run", lambda transport: order.append("run"))
    mcp_server.main()
    assert order == ["log", "upgrade", "preload", "pull", "run"]
    order.clear()
    monkeypatch.setattr(migrations, "_state", NEWER)
    mcp_server.main()
    assert "pull" not in order and order[-1] == "run"


def test_doctor_names_the_state_of_the_data(monkeypatch, tmp_path):
    from door.core import doctor

    kwargs = dict(which=lambda name: None, find_spec=lambda name: None, run=lambda *a, **k: None, repo_root=tmp_path)
    monkeypatch.setattr(doctor, "check_serve_instances", lambda: None)
    ok = doctor.run_checks(tmp_path / "profile", tmp_path / "jobs", **kwargs)
    assert ok["data"] == {"state": "ok", "message": ""}
    monkeypatch.setattr(migrations, "_state", FAILED)
    assert doctor.run_checks(tmp_path / "profile", tmp_path / "jobs", **kwargs)["data"] == FAILED
