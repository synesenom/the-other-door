"""What lands in the problem log (#593) from the MCP server, the CLI and a `find` run."""

import asyncio

import click
import mcp.shared.memory as mcp_client
import pytest
from click.testing import CliRunner

import door.mcp_server as server
from door.cli import cli
from door.commands import find as find_cmd
from door.commands import market as market_cmd
from door.core import problem_log, workspace


@pytest.fixture
def log(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    path = problem_log.setup(home)
    yield path
    problem_log.close()


def _call(tool: str, args: dict):
    async def run():
        async with mcp_client.create_connected_server_and_client_session(server.mcp) as client:
            return await client.call_tool(tool, args)

    return asyncio.run(run())


def test_a_tool_answering_an_error_is_logged_with_its_name(log, tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "JOBS_DIR", tmp_path / "jobs")
    _call("show", {"job_id": "missing"})
    assert "ERROR tool show: no posting found for job_id 'missing'" in log.read_text(encoding="utf-8")


def test_the_arguments_of_a_failed_call_are_not_logged(log, monkeypatch):
    from door.commands import profile as profile_cmd

    def refuse(markdown):
        raise ValueError("the CV could not be saved")

    monkeypatch.setattr(profile_cmd, "_save_cv_core", refuse)
    _call("save_cv", {"markdown": "# Ada Lovelace\nSecret CV text"})
    text = log.read_text(encoding="utf-8")
    assert "ERROR tool save_cv: the CV could not be saved" in text
    assert "Secret CV text" not in text and "Lovelace" not in text


def test_a_tool_that_crashes_is_logged(log, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("the market fell over")

    monkeypatch.setattr(market_cmd, "_market_core", broken)
    result = _call("market", {})
    assert result.isError
    assert "ERROR tool market: RuntimeError: the market fell over" in log.read_text(encoding="utf-8")


def test_a_warning_a_tool_returns_is_logged(log, monkeypatch):
    monkeypatch.setattr(market_cmd, "_market_core", lambda *a, **k: {"warning": "grouping the skills failed"})
    _call("market", {})
    assert "WARNING tool market: grouping the skills failed" in log.read_text(encoding="utf-8")


def test_a_good_answer_logs_nothing(log, monkeypatch):
    monkeypatch.setattr(market_cmd, "_market_core", lambda *a, **k: {"warning": None, "report_path": "x"})
    _call("market", {})
    assert not log.exists()


def test_a_command_that_crashes_is_logged(log, monkeypatch):
    @click.command("boom")
    def boom():
        raise RuntimeError("kaput")

    monkeypatch.setitem(cli.commands, "boom", boom)
    result = CliRunner().invoke(cli, ["boom"])
    assert isinstance(result.exception, RuntimeError)
    assert "ERROR command boom: RuntimeError: kaput" in log.read_text(encoding="utf-8")


def test_a_command_that_exits_on_purpose_is_not_a_crash(log, monkeypatch):
    @click.command("fine")
    def fine():
        raise click.UsageError("say it differently")

    monkeypatch.setitem(cli.commands, "fine", fine)
    CliRunner().invoke(cli, ["fine"])
    assert not log.exists()


def test_a_run_record_written_by_find_is_logged(log, tmp_path):
    record = {
        "started_at": "2026-10-26T09:00:00+00:00", "elapsed_s": 3.0, "new_above_threshold": [], "failures": ["thehub"],
        "search": {"summary": "0 postings", "sites": [{"site": "thehub", "outcome": "failed", "errors": ["HTTP 503"]}]},
    }
    find_cmd._write_run_record(record, tmp_path / "jobs", 0.65)
    assert "ERROR site thehub failed: HTTP 503" in log.read_text(encoding="utf-8")


def test_a_prepare_readback_warning_is_not_logged_but_its_error_is(log):
    server._log_answer("prepare", {"outcome": "prepared", "warning": "the PDFs may not read back cleanly"})
    assert not log.exists()
    server._log_answer("prepare", {"error": "tailor step failed"})
    assert "ERROR tool prepare: tailor step failed" in log.read_text(encoding="utf-8")
    server._log_answer("market", {"warning": "grouping failed"})
    assert "WARNING tool market: grouping failed" in log.read_text(encoding="utf-8")
