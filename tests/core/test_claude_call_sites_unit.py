"""Every place that starts `claude -p`, against every property each must have (#575).

One row per call site, one assertion block per property: the call asks for the stream
(`--output-format stream-json --verbose`), runs on the plan `claude_config_dir` names with no
parent Claude Code session leaking in, and appends one `jobs/usage.jsonl` line under its
feature with the envelope's cost and the plan's windows.

Offline: `subprocess.run` (or the call site's `run` seam) is replaced; nothing calls `claude`.
"""

import json
import subprocess
import types

import pytest

from door.commands import prepare as prepare_cmd
from door.core import scraper_fix, usage, workspace
from door.matching import language, scorer
from door.matching.language import _run_claude as real_language_run_claude  # conftest stubs the attribute

_EVENT = {"type": "rate_limit_event", "rate_limit_info": {
    "status": "allowed", "unifiedWindows": {"five_hour": {"utilization": 0.2, "resetsAt": 5},
                                            "seven_day": {"utilization": 0.6, "resetsAt": 9}}}}
_READING = {"u5": 0.2, "r5": 5, "u7": 0.6, "r7": 9, "status": "allowed"}
_COST = 0.004


def _stdout(result: str) -> str:
    envelope = {"type": "result", "subtype": "success", "is_error": False, "result": result, "total_cost_usd": _COST}
    return "\n".join(json.dumps(m) for m in ({"type": "system"}, _EVENT, envelope)) + "\n"


def _scored(ids):
    return json.dumps({"results": [{"job_id": i, "score": 0.5, "score_reason": "r", "matching_skills": [],
                                    "missing_skills": [], "flags": [], "language_requirement": "none"} for i in ids]})


def _capture(calls, stdout):
    def run(argv, **kwargs):
        calls.append((argv, kwargs.get("env")))
        return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    return run


def _scoring(calls, tmp_path, monkeypatch):
    ids = ["s.1", "s.2", "s.3"]
    postings = [{"id": i, "title": "t", "company": "c", "description": "d"} for i in ids]
    results, failed = scorer.score_postings(postings, system_prompt="s", chunk=3, workers=1,
                                            run_fn=_capture(calls, _stdout(_scored(ids))), sleep_fn=lambda s: None)[:2]
    assert set(results) == set(ids) and not failed
    return "match_scoring", 3


def _title_translation(calls, tmp_path, monkeypatch):
    path = tmp_path / "a.json"
    path.write_text(json.dumps({"id": "s.1", "title": "Udvikler", "description": "Vi søger en udvikler", "language": "da"}))
    stdout = _stdout(json.dumps({"titles": [{"id": "s.1", "title_en": "Developer"}]}))
    run = _capture(calls, stdout)
    language.filter_languages([path], {"languages": ["English", "Danish"]},
                              run_fn=lambda argv, stdin: real_language_run_claude(argv, stdin, which=lambda n: "/bin/claude",
                                                                                   run=run))
    assert json.loads(path.read_text())["title_en"] == "Developer"
    return "title_translation", None


def _tailor(calls, tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _capture(calls, _stdout("done")))
    assert prepare_cmd._run_tailor("s.1", tmp_path / "posting.json") is True
    return "tailoring", None


def _scraper_fixer(calls, tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _capture(calls, _stdout("fixed")))
    assert scraper_fix._run_scraper_fixer("jobindex", tmp_path / "raw.html", repo_root=tmp_path) == "fixed"
    return "scraper_fix", None


@pytest.mark.parametrize("call_site", [_scoring, _title_translation, _tailor, _scraper_fixer],
                         ids=lambda f: f.__name__.strip("_"))
def test_each_claude_call_site(call_site, tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "config.json").write_text(json.dumps({"claude_config_dir": "/plans/personal"}))
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("KEEP_ME", "yes")

    calls = []
    feature, units = call_site(calls, tmp_path, monkeypatch)

    [(argv, env)] = calls
    # asks for the stream, which carries the plan's windows
    assert argv[argv.index("--output-format") + 1] == "stream-json" and "--verbose" in argv
    # no MCP server of the user's: ~34k input tokens a call (#345); the tailor's own door server is named by --mcp-config
    assert "--strict-mcp-config" in argv
    if feature == "tailoring":
        assert list(json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]) == ["door"]
    else:
        assert "--mcp-config" not in argv
    # the configured plan, and no parent session
    assert env["CLAUDE_CONFIG_DIR"] == "/plans/personal" and env["KEEP_ME"] == "yes"
    assert "CLAUDECODE" not in env and not [k for k in env if k.startswith("CLAUDE_CODE_")]
    # one usage line: its feature, the envelope's cost and the plan's windows
    [line] = usage.read()
    assert line["feature"] == feature and line["weight"] == _COST
    assert {k: line[k] for k in _READING if k in line} == _READING
    if units is not None:
        assert line["units"] == units
