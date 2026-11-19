"""Inferring the profile basics (`_infer_basics_core`, the `infer_basics` tool): name, email, city, ad languages and
a `remote` default from the CV draft. `missing` is the only reason a flow asks a question.

Offline: `claude_cli.run` is replaced; nothing is executed.
"""

import types

import pytest

from door.commands import cv as cv_cmd
from door.core import claude_cli, cv_read, workspace
import cv_read_utils
from paths import REPO_ROOT

HEADER = "# Jane Doe\n\n**Phone:** TODO | **Email:** jane@example.com | **Location:** Frederiksberg, Denmark\n\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "PROFILE_EXAMPLE_DIR", REPO_ROOT / "profile.example")
    return types.SimpleNamespace(profile_dir=profile_dir)


def _reading(monkeypatch, calls=None, **fields):
    """`cv_read._ask` answers with the plain reading of the CV it is asked about, `fields` replaced."""
    def ask(md):
        if calls is not None:
            calls.append(md)
        return {**cv_read_utils.fake_ask(md), **fields}
    monkeypatch.setattr(cv_read, "_ask", ask)


def _no_model(monkeypatch):
    monkeypatch.setattr(cv_read, "_ask", lambda md: pytest.fail("this needs no model call"))


def _infer(env, text):
    return cv_cmd._infer_basics_core(text, profile_dir=env.profile_dir)


def test_a_full_english_header_is_read_in_one_call(env, monkeypatch):
    calls = []
    _reading(monkeypatch, calls)
    assert _infer(env, HEADER + "## Profile\n\nData scientist.\n") == {
        "name": "Jane Doe", "email": "jane@example.com", "location": "Copenhagen", "languages": ["English"],
        "remote": "hybrid", "missing": [],
    }
    assert len(calls) == 1


def test_it_reads_the_draft_when_no_text_is_given(env, monkeypatch):
    _reading(monkeypatch)
    (env.profile_dir / "cv.draft.md").write_text(HEADER)
    assert cv_cmd._infer_basics_core(profile_dir=env.profile_dir)["name"] == "Jane Doe"


def test_a_todo_is_not_an_answer(env, monkeypatch):
    _reading(monkeypatch)
    result = _infer(env, "# TODO\n\n**Email:** TODO | **Location:** TODO\n")
    assert (result["name"], result["email"], result["location"]) == (None, None, None)
    assert result["missing"] == ["name", "email", "location"]


def test_a_city_in_a_country_not_covered_is_unsupported(env, monkeypatch):
    _reading(monkeypatch, country="de")
    result = _infer(env, "# Jane Doe\n\n**Email:** j@example.org | **Location:** Berlin, Germany\n")
    assert result["location"] is None and result["unsupported_location"] == "Berlin, Germany"
    assert result["missing"] == ["location"]


def test_a_city_in_a_covered_country_that_is_not_listed_is_only_missing(env, monkeypatch):
    _reading(monkeypatch, country="dk")
    result = _infer(env, "# Jane Doe\n\n**Email:** j@example.org | **Location:** Vejle\n")
    assert result["location"] is None and "unsupported_location" not in result
    assert result["missing"] == ["location"]


def test_a_country_alone_is_no_city(env, monkeypatch):
    _reading(monkeypatch, country="dk")
    result = _infer(env, "# Jane Doe\n\n**Email:** j@example.com | **Location:** Denmark\n")
    assert result["location"] is None and "unsupported_location" not in result
    assert result["missing"] == ["location"]


def test_the_city_of_the_current_job_is_taken_when_the_header_has_none(env, monkeypatch):
    _reading(monkeypatch, city="Århus", country="dk")
    result = _infer(env, "# Jane Doe\n\n**Email:** j@example.com\n\n### Analyst | Acme, Århus — 2020 - present\n")
    assert result["location"] == "Aarhus" and result["missing"] == []


def test_languages_at_a_working_level_count_and_english_is_always_in(env, monkeypatch):
    _reading(monkeypatch, languages=[
        {"language": "Danish", "code": "da", "level": "fluent"}, {"language": "Hungarian", "code": "hu", "level": "basic"},
        {"language": "German", "code": "de", "level": "native"}, {"language": "Swedish", "code": "sv", "level": "working"},
        {"language": "Italian", "code": "it", "level": "conversational"},
    ])
    result = _infer(env, HEADER + "## Languages\n\nDanish (fluent), Hungarian (basic), German (native), Swedish (working), Italian (conversational)\n")
    assert result["languages"] == ["English", "Danish", "Swedish"]


@pytest.mark.parametrize("language, code, level, shown", [("Dansk", "da", "native", "Danish"), ("Français", "fr", "fluent", "French"),
                                                          ("magyar", "hu", "working", "Hungarian"), ("Svenska", "sv", "fluent", "Swedish")])
def test_a_cv_in_another_supported_language_is_read_the_same_way(env, monkeypatch, language, code, level, shown):
    _reading(monkeypatch, languages=[{"language": language, "code": code, "level": level}])
    result = _infer(env, HEADER + f"## Sprog\n\n- {language}: {level}\n")
    assert result["languages"] == ["English", shown]


def test_an_unreadable_cv_asks_instead_and_never_stops(env, monkeypatch):
    def boom(md):
        raise claude_cli.ClaudeError("not logged in")
    monkeypatch.setattr(cv_read, "_ask", boom)
    result = _infer(env, "# Jane Doe\n\n**Email:** j@example.com\n")
    assert (result["name"], result["email"], result["location"]) == (None, None, None)
    assert result["missing"] == ["name", "email", "location"] and result["languages"] == ["English"]
    assert "not logged in" in result["warning"]


@pytest.mark.parametrize("cv", [None, "example"])
def test_no_cv_of_the_users_own_leaves_everything_to_ask(env, monkeypatch, cv):
    _no_model(monkeypatch)
    if cv:
        (env.profile_dir / "cv.md").write_text((workspace.PROFILE_EXAMPLE_DIR / "cv.md").read_text())
    result = cv_cmd._infer_basics_core(profile_dir=env.profile_dir)
    assert result["missing"] == ["name", "email", "location"]
    assert result["languages"] == ["English"] and result["remote"] == "hybrid"


# --- a tagline and LinkedIn / GitHub parts in the header (#189) ---------------------------------------------

EXTENDED = (
    "# Jane Doe\n\n> Financial Controller | Group Reporting & Process Improvement\n\n"
    "**Phone:** +45 00 00 00 00 | **Email:** jane@example.com | **Web:** janedoe.example.com | "
    "**LinkedIn:** https://www.linkedin.com/in/janedoe | **GitHub:** https://github.com/janedoe | "
    "**Location:** Frederiksberg, Denmark\n\n"
)


def test_a_tagline_with_a_bar_and_the_link_parts_do_not_disturb_the_basics(env, monkeypatch):
    _reading(monkeypatch)
    assert _infer(env, EXTENDED + "## Profile\n\nController.\n") == {
        "name": "Jane Doe", "email": "jane@example.com", "location": "Copenhagen", "languages": ["English"],
        "remote": "hybrid", "missing": [],
    }


def test_the_draft_rules_say_the_tagline_and_links_are_written_only_when_a_source_gives_them():
    rules = cv_cmd._RULES
    assert "tagline" in rules and "LinkedIn" in rules and "GitHub" in rules
    assert "never a `TODO`" in rules.split("tagline", 1)[1]


def test_the_example_cv_has_a_tagline_under_the_name_and_parses(env, monkeypatch):
    _reading(monkeypatch)
    text = (REPO_ROOT / "profile.example" / "cv.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "# Jane Doe" and lines[2].startswith("> ")
    assert "**LinkedIn:**" in text and "**GitHub:**" in text
    found = _infer(env, text)
    assert found["name"] == "Jane Doe" and found["location"] == "Copenhagen" and found["email"] == "jane.doe@example.com"
