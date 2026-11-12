"""`ask` (#339): one question about the jobs data, answered by Haiku with the read tools only."""

import json

import pytest
from click.testing import CliRunner

from cli_utils import result_text, write_list_posting
from door.cli import cli
from door.commands import ask as ask_cmd
from door.core import claude_cli, workspace
import door.mcp_server as server


def _answer(monkeypatch, answer, calls=None):
    def fake_run(args, *, input=None, timeout_s=None, profile_dir=None, **_):
        if calls is not None:
            calls.append({"args": args, "input": input, "timeout_s": timeout_s})
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps({"type": "result", "is_error": False, "result": json.dumps(answer)})

    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(workspace, "ensure_mcp_config", lambda: workspace.REPO_ROOT / ".mcp.json")


def test_one_call_with_the_read_tools_only(cli_env, monkeypatch):
    calls = []
    _answer(monkeypatch, {"answer": "You applied to 2 jobs in September.", "sources": ["query_jobs"]}, calls)
    result = ask_cmd._ask_core("How many jobs did I apply to in September?", jobs_dir=cli_env.jobs_dir)
    assert result == {"answer": "You applied to 2 jobs in September.", "go_to": None, "sources": ["query_jobs"]}
    args = calls[0]["args"]
    assert calls[0]["input"] == "How many jobs did I apply to in September?"
    allowed = args[args.index("--allowedTools") + 1].split(",")
    assert allowed == [f"mcp__door__{t}" for t in ask_cmd.ASK_TOOLS]
    assert args[args.index("--mcp-config") + 1].endswith(".mcp.json")
    assert "--json-schema" in args and "--no-session-persistence" in args
    assert args[args.index("--model") + 1] == "haiku"
    disallowed = args[args.index("--disallowedTools") + 1].split(",")
    for tool in ("Bash", "Write", "Edit", "Read", "mcp__door__set_status", "mcp__door__find_jobs", "mcp__door__ask", "mcp__door__show"):
        assert tool in disallowed
    # only The other door's server (not the user's own MCP servers or connectors), and no built-in tool at all
    assert "--strict-mcp-config" in args
    assert args[args.index("--tools") + 1] == ""


def test_the_read_tools_never_include_a_writing_one():
    # Every tool is classified once (mcp_server.READ_ONLY_TOOLS or WRITING_TOOLS), so a new tool must be placed.
    every = {t.name for t in server.mcp._tool_manager.list_tools()}
    assert server.READ_ONLY_TOOLS | server.WRITING_TOOLS == every
    assert not server.READ_ONLY_TOOLS & server.WRITING_TOOLS
    assert set(ask_cmd.ASK_TOOLS) <= server.READ_ONLY_TOOLS
    assert "ask" not in ask_cmd.ASK_TOOLS and "market" not in ask_cmd.ASK_TOOLS
    # show can open the PDF viewer and render page images under jobs/output/: not read-only
    assert "show" in server.WRITING_TOOLS and "show" not in ask_cmd.ASK_TOOLS


def test_go_to_keeps_only_jobs_that_exist(cli_env, monkeypatch):
    write_list_posting(cli_env.jobs_dir, "2026-09-03", "jobindex", "jobindex.1", title="Data Analyst")
    _answer(monkeypatch, {"answer": "Two interviews.", "go_to": {"screen": "applications", "job_ids": ["jobindex.1", "made.up"]}, "sources": []})
    result = ask_cmd._ask_core("show me the interviews", jobs_dir=cli_env.jobs_dir)
    assert result["go_to"] == {"screen": "applications", "job_ids": ["jobindex.1"]}


def test_an_unknown_screen_is_dropped(cli_env, monkeypatch):
    _answer(monkeypatch, {"answer": "x", "go_to": {"screen": "/etc/passwd"}, "sources": []})
    assert ask_cmd._ask_core("q", jobs_dir=cli_env.jobs_dir)["go_to"] is None


@pytest.mark.parametrize("bad", ["not json at all", claude_cli.ClaudeError("claude -p timed out after 180s"),
                                 json.dumps({"type": "result", "is_error": True, "result": "overloaded"}),
                                 json.dumps({"type": "result", "is_error": False, "result": json.dumps({"go_to": None})})])
def test_a_failed_answer_is_an_error_not_a_crash(cli_env, monkeypatch, bad):
    _answer(monkeypatch, bad)
    with pytest.raises(claude_cli.ClaudeError):
        ask_cmd._ask_core("q", jobs_dir=cli_env.jobs_dir)


def test_an_empty_question_is_refused(cli_env):
    with pytest.raises(ValueError):
        ask_cmd._ask_core("   ", jobs_dir=cli_env.jobs_dir)


def test_the_command_prints_the_answer_and_where_it_points(cli_env, monkeypatch):
    write_list_posting(cli_env.jobs_dir, "2026-09-03", "jobindex", "jobindex.1", title="Data Analyst", company="Acme")
    _answer(monkeypatch, {"answer": "One: Data Analyst at Acme.", "go_to": {"screen": "posting", "job_ids": ["jobindex.1"]}, "sources": ["show"]})
    result = CliRunner().invoke(cli, ["ask", "which one is in Copenhagen?"])
    assert result.exit_code == 0, result_text(result)
    text = result_text(result)
    assert "One: Data Analyst at Acme." in text
    assert "See: Data Analyst · Acme" in text
    assert "jobindex.1" not in text


def test_the_tool_answers_the_same(cli_env, monkeypatch):
    _answer(monkeypatch, {"answer": "Nothing yet.", "sources": []})
    assert server.ask("anything new?") == {"answer": "Nothing yet.", "go_to": None, "sources": []}
    _answer(monkeypatch, claude_cli.ClaudeError("claude exited 1: boom"))
    assert "boom" in server.ask("anything new?")["error"]
