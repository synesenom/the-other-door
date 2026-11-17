"""`claude_cli.read_stream`: the result envelope and the plan's limits from a
`claude -p --output-format stream-json --verbose` call (#575, plan §4).

Offline: the fixture is a real call's stream (ids scrubbed); nothing calls `claude`.
"""

import json
import subprocess

import pytest

from door.core import claude_cli, usage
from paths import TESTS_DIR

FIXTURE = TESTS_DIR / "core" / "fixtures" / "claude" / "stream_rate_limit.jsonl"


def _stream(*messages) -> str:
    return "\n".join(json.dumps(m) for m in messages) + "\n"


def _result(result="hi", cost=0.002, **extra):
    return {"type": "result", "subtype": "success", "is_error": False, "result": result,
            "total_cost_usd": cost, **extra}


def _limit(info):
    return {"type": "rate_limit_event", "rate_limit_info": info}


def test_the_saved_stream_gives_its_envelope_and_both_windows():
    envelope, limits = claude_cli.read_stream(FIXTURE.read_text(encoding="utf-8"))
    env = json.loads(envelope)
    assert env["type"] == "result" and env["structured_output"] == {"n": 3}
    assert claude_cli.json_result(envelope) == {"n": 3}
    assert usage.weight(envelope) == env["total_cost_usd"]
    assert limits == {
        "status": "allowed",
        "five_hour": {"used": 0.09, "resets_at": 1793749200, "status": "allowed"},
        "seven_day": {"used": 0.54, "resets_at": 1794034800, "status": "allowed"},
    }


def test_a_stream_without_a_rate_limit_event_has_no_limits():
    envelope, limits = claude_cli.read_stream(_stream({"type": "system", "subtype": "init"}, _result()))
    assert json.loads(envelope)["result"] == "hi"
    assert limits is None


def test_the_last_rate_limit_event_wins():
    first = _limit({"status": "allowed", "unifiedWindows": {"five_hour": {"utilization": 0.1, "resetsAt": 1}}})
    last = _limit({"status": "allowed_warning", "unifiedWindows": {"five_hour": {"utilization": 0.8, "resetsAt": 2}}})
    _, limits = claude_cli.read_stream(_stream(first, last, _result()))
    assert limits == {"status": "allowed_warning", "five_hour": {"used": 0.8, "resets_at": 2}}


def test_a_plain_envelope_is_its_own_envelope():
    plain = json.dumps(_result(result="x"), indent=2)  # one JSON value, even over several lines
    assert claude_cli.read_stream(plain) == (plain, None)


@pytest.mark.parametrize("stdout", ["", None, "not json", "[1]\n[2]\n", _stream({"type": "system"})])
def test_no_result_line_means_no_envelope(stdout):
    envelope, _ = claude_cli.read_stream(stdout)
    assert envelope is None


def test_a_garbled_line_is_skipped():
    _, limits = claude_cli.read_stream("{oops\n" + _stream(
        _limit({"unifiedWindows": {"seven_day": {"utilization": 0.3}}}), _result()))
    assert limits == {"seven_day": {"used": 0.3}}


@pytest.mark.parametrize("value, used", [(0.42, 0.42), (42, 0.42), (1, 1.0), (150, 1.0), (-3, 0.0)])
def test_utilization_is_a_fraction(value, used):
    _, limits = claude_cli.read_stream(_stream(_limit({"unifiedWindows": {"five_hour": {"utilization": value}}})))
    assert limits["five_hour"]["used"] == used


def test_without_unified_windows_the_top_level_utilization_names_its_window():
    _, limits = claude_cli.read_stream(_stream(_limit(
        {"status": "allowed", "rateLimitType": "five_hour", "utilization": 0.25, "resetsAt": 99})))
    assert limits == {"status": "allowed", "five_hour": {"used": 0.25, "resets_at": 99}}


def test_status_and_reset_alone_are_kept():
    _, limits = claude_cli.read_stream(_stream(_limit({"status": "rejected", "rateLimitType": "five_hour", "resetsAt": 7})))
    assert limits == {"status": "rejected", "five_hour": {"resets_at": 7}}


@pytest.mark.parametrize("info", [{}, {"status": 3}, {"unifiedWindows": {"five_hour": {"utilization": "a", "resetsAt": True}}},
                                  {"unifiedWindows": {"weird_window": {"utilization": 0.5}}}, "not a dict"])
def test_unusable_limits_are_none(info):
    _, limits = claude_cli.read_stream(_stream(_limit(info), _result()))
    assert limits is None


# --------------------------------------------------------------------------- the call sites read streams
def _fake_run(calls, stdout, rc=0):
    def fake(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, rc, stdout=stdout, stderr="")
    return fake


def test_run_asks_for_nothing_itself_but_returns_the_envelope_of_a_stream(monkeypatch):
    stdout = _stream(_limit({"status": "allowed"}), _result(result="answer", cost=0.03))
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run([], stdout))
    out = claude_cli.run(claude_cli.STREAM_ARGS, feature="revise")
    assert claude_cli.envelope_result(out) == "answer"
    assert usage.read()[0]["weight"] == 0.03


def test_run_returns_what_is_no_stream_unchanged(monkeypatch):
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run([], "plain words"))
    assert claude_cli.run([], feature="ask") == "plain words"


def test_ask_reads_a_stream(monkeypatch):
    calls = []
    stdout = _stream({"type": "system"}, _result(result=json.dumps({"a": 1}), structured_output={"a": 1}))
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run(calls, stdout))
    assert claude_cli.ask("sys", "q", model="haiku", feature="keywords", schema={"type": "object"}) == {"a": 1}
    argv = calls[0]
    assert argv[argv.index("--output-format") + 1] == "stream-json" and "--verbose" in argv


def test_ask_passes_effort_and_strict_mcp_when_asked(monkeypatch):
    calls = []
    stdout = _stream(_result(result="{}", structured_output={}))
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run(calls, stdout))
    claude_cli.ask("sys", "q", model="haiku", feature="style", schema={"type": "object"}, effort="low", strict_mcp=True)
    argv = calls[0]
    assert argv[argv.index("--effort") + 1] == "low" and "--strict-mcp-config" in argv


def test_ask_adds_neither_flag_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run(calls, _stream(_result(result="x"))))
    claude_cli.ask("sys", "q", model="haiku", feature="keywords")
    assert "--effort" not in calls[0] and "--strict-mcp-config" not in calls[0]


# --------------------------------------------------------------------------- the call sites record the limits (plan §5)
_EVENT = _limit({"status": "allowed", "unifiedWindows": {"five_hour": {"utilization": 0.2, "resetsAt": 5},
                                                         "seven_day": {"utilization": 0.6, "resetsAt": 9}}})
_READING = {"u5": 0.2, "r5": 5, "u7": 0.6, "r7": 9, "status": "allowed"}


def _reading(line):
    return {k: line[k] for k in _READING if k in line}


def test_run_records_the_limits(monkeypatch):
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run([], _stream(_EVENT, _result())))
    claude_cli.run(claude_cli.STREAM_ARGS, feature="revise")
    assert _reading(usage.read()[0]) == _READING


