"""`claude_cli.run` / `json_result`: the one way a command calls `claude -p`.

Offline: `subprocess.run` is replaced; nothing is executed.
"""

import json
import subprocess

import pytest

from door.core import claude_cli, workspace
from profile_utils import write_config


def _fake_run(calls, *, rc=0, stdout="", stderr="", raise_exc=None):
    def fake(argv, **kwargs):
        calls.append((argv, kwargs))
        if raise_exc is not None:
            raise raise_exc
        return subprocess.CompletedProcess(argv, rc, stdout=stdout, stderr=stderr)
    return fake


def test_run_calls_claude_in_print_mode_from_the_repo_root(monkeypatch):
    calls = []
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run(calls, stdout="hi"))
    assert claude_cli.run(["--model", "haiku"], input="q", timeout_s=5, feature="ask") == "hi"
    argv, kwargs = calls[0]
    assert argv[:2] == ["claude", "-p"]
    assert argv[2:] == ["--model", "haiku"]
    assert kwargs["input"] == "q"
    assert kwargs["timeout"] == 5
    assert kwargs["cwd"] == workspace.REPO_ROOT
    assert kwargs["capture_output"] and kwargs["text"]


def test_run_uses_the_profiles_plan_and_a_fresh_session(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run(calls))
    monkeypatch.setenv("CLAUDE_CODE_SSE_PORT", "1")
    monkeypatch.setenv("CLAUDECODE", "1")
    write_config(tmp_path / "profile", {"claude_config_dir": str(tmp_path / "plan")})
    claude_cli.run([], profile_dir=tmp_path / "profile", feature="ask")
    env = calls[0][1]["env"]
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "plan")
    assert "CLAUDE_CODE_SSE_PORT" not in env and "CLAUDECODE" not in env


@pytest.mark.parametrize(
    "exc, message",
    [
        (subprocess.TimeoutExpired(["claude"], 7), "timed out after 7s"),
        (FileNotFoundError("claude"), "could not invoke `claude` CLI"),
    ],
)
def test_run_wraps_failures_in_claude_error(monkeypatch, exc, message):
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run([], raise_exc=exc))
    with pytest.raises(claude_cli.ClaudeError, match=message):
        claude_cli.run([], timeout_s=7, feature="ask")


def test_run_reports_a_non_zero_exit_with_stderr(monkeypatch):
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run([], rc=1, stderr="rate limited"))
    with pytest.raises(claude_cli.ClaudeError, match="claude exited 1: rate limited"):
        claude_cli.run([], feature="ask")


def test_json_result_parses_the_envelopes_result():
    assert claude_cli.json_result(json.dumps({"result": json.dumps({"a": [1]})})) == {"a": [1]}
    assert claude_cli.json_result(json.dumps({"result": {"a": 1}})) == {"a": 1}


@pytest.mark.parametrize(
    "stdout, message",
    [
        ("not json", "no JSON envelope"),
        ("[1]", "no JSON envelope"),
        (json.dumps({"is_error": True, "result": "boom"}), "reported an error"),
        (json.dumps({"result": "plain text"}), "not JSON"),
    ],
)
def test_json_result_rejects_bad_envelopes(stdout, message):
    with pytest.raises(claude_cli.ClaudeError, match=message):
        claude_cli.json_result(stdout)


def test_run_uses_the_resolved_claude_path(monkeypatch):
    from door.core import installers

    calls = []
    monkeypatch.setattr(installers, "find_claude", lambda *a, **k: "/x/claude")
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run(calls, stdout="hi"))
    claude_cli.run([], feature="ask")
    assert calls[0][0][0] == "/x/claude"


# --------------------------------------------------------------------------- usage (#575)
def _env(result="hi", out=40, is_error=False):
    return json.dumps({"type": "result", "is_error": is_error, "result": result, "total_cost_usd": 0.002,
                       "duration_ms": 900, "modelUsage": {"m": {"inputTokens": 10, "outputTokens": out}}})


def test_run_records_the_calls_usage_under_its_feature(monkeypatch):
    from door.core import usage
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run([], stdout=_env()))
    claude_cli.run(["--model", "haiku"], feature="revise")
    [line] = usage.read()
    assert (line["feature"], line["weight"]) == ("revise", 0.002)


def test_run_records_a_failed_call_that_reported_usage(monkeypatch):
    from door.core import usage
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run([], rc=1, stdout=_env(is_error=True), stderr="boom"))
    with pytest.raises(claude_cli.ClaudeError):
        claude_cli.run([], feature="ask")
    assert usage.read()[0]["feature"] == "ask"


def test_run_needs_a_feature():
    with pytest.raises(TypeError):
        claude_cli.run([])


def test_ask_without_a_schema_reads_the_envelope_text(monkeypatch):
    from door.core import usage
    calls = []
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run(calls, stdout=_env(result="  the report \n")))
    assert claude_cli.ask("sys", "q", model="sonnet", feature="skill_gaps") == "the report"
    argv = calls[0][0]
    assert argv[argv.index("--output-format") + 1] == "stream-json" and "--verbose" in argv
    assert "--json-schema" not in argv
    assert usage.read()[0]["feature"] == "skill_gaps"
