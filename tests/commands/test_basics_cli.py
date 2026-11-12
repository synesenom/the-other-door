"""Inferring the profile basics (`_infer_basics_core`, the `infer_basics` tool): name, email, city, ad languages and
a `remote` default from the CV draft. `missing` is the only reason a flow asks a question.

Offline: `claude_cli.run` is replaced; nothing is executed.
"""

import json
import types

import pytest

import door.mcp_server as server
from door.commands import cv as cv_cmd
from door.core import claude_cli, workspace
from paths import REPO_ROOT

HEADER = "# Jane Doe\n\n**Phone:** TODO | **Email:** jane@example.com | **Location:** Frederiksberg, Denmark\n\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "PROFILE_EXAMPLE_DIR", REPO_ROOT / "profile.example")
    return types.SimpleNamespace(profile_dir=profile_dir)


def _answer(monkeypatch, calls=None, **fields):
    answer = {"name": None, "email": None, "city": None, "languages": [], **fields}

    def fake_run(args, *, input=None, timeout_s=None, profile_dir=None, **_):
        if calls is not None:
            calls.append({"args": args, "input": input})
        return json.dumps({"result": json.dumps(answer)})
    monkeypatch.setattr(claude_cli, "run", fake_run)


def _no_model(monkeypatch):
    monkeypatch.setattr(claude_cli, "run", lambda *a, **k: pytest.fail("this needs no model call"))


def _infer(env, text):
    return cv_cmd._infer_basics_core(text, profile_dir=env.profile_dir)


def test_a_full_english_header_needs_no_model(env, monkeypatch):
    _no_model(monkeypatch)
    assert _infer(env, HEADER + "## Profile\n\nData scientist.\n") == {
        "name": "Jane Doe", "email": "jane@example.com", "location": "Copenhagen", "languages": ["English"],
        "remote": "hybrid", "missing": [],
    }


def test_it_reads_the_draft_when_no_text_is_given(env, monkeypatch):
    _no_model(monkeypatch)
    (env.profile_dir / "cv.draft.md").write_text(HEADER)
    assert cv_cmd._infer_basics_core(profile_dir=env.profile_dir)["name"] == "Jane Doe"


def test_a_todo_is_not_an_answer(env, monkeypatch):
    _answer(monkeypatch)
    result = _infer(env, "# TODO\n\n**Email:** TODO | **Location:** TODO\n")
    assert (result["name"], result["email"], result["location"]) == (None, None, None)
    assert result["missing"] == ["name", "email", "location"]


def test_a_city_outside_the_covered_countries_is_unsupported(env, monkeypatch):
    _no_model(monkeypatch)
    result = _infer(env, "# Jane Doe\n\n**Email:** j@example.org | **Location:** Berlin, Germany\n")
    assert result["location"] is None and result["unsupported_location"] == "Berlin, Germany"
    assert result["missing"] == ["location"]


def test_the_model_finds_a_city_the_header_does_not_name(env, monkeypatch):
    calls = []
    _answer(monkeypatch, calls, city="Århus")
    result = _infer(env, "# Jane Doe\n\n**Email:** j@example.com\n\n### Analyst | Acme, Aarhus — 2020 - present\n")
    assert result["location"] == "Aarhus" and result["missing"] == []
    args = calls[0]["args"]
    assert args[args.index("--model") + 1] == cv_cmd._BASICS_MODEL and "Acme, Aarhus" in calls[0]["input"]


def test_a_country_alone_is_no_city(env, monkeypatch):
    _answer(monkeypatch)
    result = _infer(env, "# Jane Doe\n\n**Email:** j@example.com | **Location:** Denmark\n")
    assert result["location"] is None and "unsupported_location" not in result
    assert result["missing"] == ["location"]


def test_languages_at_a_working_level_count_and_english_is_always_in(env, monkeypatch):
    _answer(monkeypatch, languages=[
        {"language": "Danish", "level": "fluent"}, {"language": "Hungarian", "level": "basic"},
        {"language": "German", "level": "native"},
    ])
    result = _infer(env, HEADER + "## Languages\n\nDanish (fluent), Hungarian (basic), German (native)\n")
    assert result["languages"] == ["English", "Danish"]


def test_only_mentioning_another_supported_language_asks_the_model(env, monkeypatch):
    calls = []
    _answer(monkeypatch, calls)
    _infer(env, HEADER + "- Dansk: flydende\n")
    assert len(calls) == 1


def test_an_invented_name_or_email_is_not_taken(env, monkeypatch):
    _answer(monkeypatch, name="John Smith", email="john@example.com", city="Copenhagen")
    result = _infer(env, "Some CV text with no header at all.\n")
    assert result["name"] is None and result["email"] is None
    assert result["missing"] == ["name", "email"]


def test_the_model_reads_a_name_and_email_from_an_odd_header(env, monkeypatch):
    _answer(monkeypatch, name="Jane Doe", email="jane@example.com", city="Odense")
    result = _infer(env, "CURRICULUM VITAE\nJane Doe\nmail jane@example.com\n")
    assert result["name"] == "Jane Doe" and result["email"] == "jane@example.com" and result["missing"] == []


def test_a_failed_call_asks_instead_and_never_stops(env, monkeypatch):
    def boom(*a, **k):
        raise claude_cli.ClaudeError("not logged in")
    monkeypatch.setattr(claude_cli, "run", boom)
    result = _infer(env, "# Jane Doe\n\n**Email:** j@example.com\n")
    assert result["name"] == "Jane Doe" and result["missing"] == ["location"]
    assert result["languages"] == ["English"] and result["warning"] == "not logged in"


@pytest.mark.parametrize("cv", [None, "example"])
def test_no_cv_of_the_users_own_leaves_everything_to_ask(env, monkeypatch, cv):
    _no_model(monkeypatch)
    if cv:
        (env.profile_dir / "cv.md").write_text((workspace.PROFILE_EXAMPLE_DIR / "cv.md").read_text())
    result = cv_cmd._infer_basics_core(profile_dir=env.profile_dir)
    assert result["missing"] == ["name", "email", "location"]
    assert result["languages"] == ["English"] and result["remote"] == "hybrid"


def test_tool_passes_its_arguments(env, monkeypatch):
    seen = {}
    monkeypatch.setattr(cv_cmd, "_infer_basics_core", lambda markdown, **kw: seen.update(markdown=markdown, **kw) or {"missing": []})
    assert server.infer_basics("# CV", model="sonnet") == {"missing": []}
    assert seen == {"markdown": "# CV", "model": "sonnet", "profile_dir": env.profile_dir}
