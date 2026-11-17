"""Inferring the profile basics (`_infer_basics_core`, the `infer_basics` tool): name, email, city, ad languages and
a `remote` default from the CV draft. `missing` is the only reason a flow asks a question.

Offline: `claude_cli.run` is replaced; nothing is executed.
"""

import json
import types

import pytest

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




# --- a tagline and LinkedIn / GitHub parts in the header (#189) ---------------------------------------------

EXTENDED = (
    "# Jane Doe\n\n> Financial Controller | Group Reporting & Process Improvement\n\n"
    "**Phone:** +45 00 00 00 00 | **Email:** jane@example.com | **Web:** janedoe.example.com | "
    "**LinkedIn:** https://www.linkedin.com/in/janedoe | **GitHub:** https://github.com/janedoe | "
    "**Location:** Frederiksberg, Denmark\n\n"
)


def test_a_tagline_with_a_bar_and_the_link_parts_do_not_disturb_the_basics(env, monkeypatch):
    _no_model(monkeypatch)
    assert _infer(env, EXTENDED + "## Profile\n\nController.\n") == {
        "name": "Jane Doe", "email": "jane@example.com", "location": "Copenhagen", "languages": ["English"],
        "remote": "hybrid", "missing": [],
    }


def test_a_header_with_only_a_tagline_is_read_like_one_without(env, monkeypatch):
    _no_model(monkeypatch)
    text = "# Jane Doe\n\n> Location: Nowhere | Email: tag@example.org\n\n" + HEADER.split("\n\n", 1)[1]
    found = _infer(env, text)
    assert found["name"] == "Jane Doe" and found["location"] == "Copenhagen"


def test_the_draft_rules_say_the_tagline_and_links_are_written_only_when_a_source_gives_them():
    rules = cv_cmd._RULES
    assert "tagline" in rules and "LinkedIn" in rules and "GitHub" in rules
    assert "never a `TODO`" in rules.split("tagline", 1)[1]


def test_the_example_cv_has_a_tagline_under_the_name_and_parses(env, monkeypatch):
    _answer(monkeypatch)  # its Danish language line is read by the model
    text = (REPO_ROOT / "profile.example" / "cv.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "# Jane Doe" and lines[2].startswith("> ")
    assert "**LinkedIn:**" in text and "**GitHub:**" in text
    found = _infer(env, text)
    assert found["name"] == "Jane Doe" and found["location"] == "Copenhagen" and found["email"] == "jane.doe@example.com"


# --- the header's labels in every supported language (#208) --------------------------------------------------------


@pytest.mark.parametrize("label", ["Lieu", "Sted", "Helyszín", "Ort", "Location"])
def test_the_location_label_is_read_in_every_supported_language(env, monkeypatch, label):
    _answer(monkeypatch)  # the model reads nothing: the place comes from the header
    result = _infer(env, f"# Jane Doe\n\n**E-mail :** jane@example.com | **{label} :** Frederiksberg\n\n## Profil\n\nx\n")
    assert (result["name"], result["email"], result["location"]) == ("Jane Doe", "jane@example.com", "Copenhagen")
    assert result["missing"] == []


def test_a_street_address_alone_is_left_to_the_model_not_called_unsupported(env, monkeypatch):
    calls = []
    _answer(monkeypatch, calls, city="Copenhagen")
    result = _infer(env, "# Jane Doe\n\n**Email:** j@example.com | **Address:** Vesterbrogade 12\n")
    assert len(calls) == 1
    assert result["location"] == "Copenhagen" and "unsupported_location" not in result and result["missing"] == []


def test_an_email_only_in_a_contact_section_is_read_without_the_model(env, monkeypatch):
    _no_model(monkeypatch)
    result = _infer(env, "# Jane Doe\n\n> tag@example.org\n\n**Location:** Copenhagen\n\n## Contact\n\n- jane@example.com\n")
    assert result["email"] == "jane@example.com" and result["missing"] == []
