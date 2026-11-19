"""`core/cv_read` (#430): the one cached reading of cv.md and what the code holds it to. The model is a patched `_ask`."""

import copy
import hashlib
import json

import pytest

from door.core import claude_cli, cv_read, templates

MD = """# Mette Berg

**Tlf:** +45 00 00 00 00 | **E-mail:** mette.berg@example.com | **By:** Aarhus

## Profil
Dataanalytiker.

## Erhvervserfaring
### Leder af analyse, Northwind Labs (2017 - nu)
- Ledede teamet.

### Dataanalytiker, Quill & Co (2010 - 2013)
- Rapporter.

## Kompetencer
Python, SQL, Docker

## Sprog
- Dansk — modersmål
- Engelsk (B2)
"""

READING = {
    "name": "Mette Berg", "email": "mette.berg@example.com", "city": "Aarhus", "country": "dk",
    "languages": [{"language": "Dansk", "level": "native"}, {"language": "Engelsk", "level": "working"}],
    "sections": [{"heading": "Profil", "kind": "summary"}, {"heading": "Erhvervserfaring", "kind": "experience"},
                 {"heading": "Kompetencer", "kind": "skills"}, {"heading": "Sprog", "kind": "languages"}],
    "contacts": [{"kind": "phone", "label": "Tlf", "value": "+45 00 00 00 00"},
                 {"kind": "email", "label": "E-mail", "value": "mette.berg@example.com"},
                 {"kind": "location", "label": "By", "value": "Aarhus"}],
    "skills": ["Python", "SQL", "Docker"],
    "levels": [{"item": "Dansk", "level": 5}, {"item": "Engelsk", "level": 3}],
    "entries": [
        {"heading": "Leder af analyse, Northwind Labs (2017 - nu)", "role": "Leder af analyse", "org": "Northwind Labs",
         "dates": "2017 - nu", "place": None, "start_year": 2017, "end_year": None},
        {"heading": "Dataanalytiker, Quill & Co (2010 - 2013)", "role": "Dataanalytiker", "org": "Quill & Co",
         "dates": "2010 - 2013", "place": None, "start_year": 2010, "end_year": 2013},
    ],
}


@pytest.fixture
def asked(monkeypatch, tmp_path):
    """Patches the model call and the cache folder; `calls` lists the CVs asked about, `answers` the replies in turn."""
    state = {"calls": [], "answers": [copy.deepcopy(READING)]}

    def fake(md):
        state["calls"].append(md)
        answer = state["answers"][min(len(state["calls"]), len(state["answers"])) - 1]
        if isinstance(answer, Exception):
            raise answer
        return copy.deepcopy(answer)

    monkeypatch.setattr(cv_read, "_ask", fake)
    monkeypatch.setattr(cv_read, "_cache_dir", lambda: tmp_path / "cache")
    return state


def _broken(**change):
    return {**copy.deepcopy(READING), **change}


def test_a_cv_in_an_unlisted_language_gets_its_kinds(asked):
    reading = cv_read.read(MD)
    assert [(s["heading"], s["kind"]) for s in reading["sections"]] == [
        ("Profil", "summary"), ("Erhvervserfaring", "experience"), ("Kompetencer", "skills"), ("Sprog", "languages")]
    assert reading["skills"] == ["Python", "SQL", "Docker"]


@pytest.mark.parametrize("change", [
    {"email": "someone.else@example.com"},
    {"name": "Anna Invented"},
    {"skills": ["Python", "Kubernetes"]},
    {"city": "Odense"},
    {"entries": [{**READING["entries"][0], "heading": "Invented heading"}]},
    {"entries": [{**READING["entries"][0], "start_year": 2016}]},
    {"entries": [{**READING["entries"][0], "end_year": 2020}]},
    {"sections": [*READING["sections"], {"heading": "Not a line", "kind": "other"}]},
    {"sections": READING["sections"][1:]},
    {"sections": [{**READING["sections"][0], "kind": "hobbies"}, *READING["sections"][1:]]},
    {"contacts": [{"kind": "fax", "label": None, "value": "Aarhus"}]},
    {"contacts": [{"kind": "phone", "label": "Tlf", "value": "+45 11 11 11 11"}]},
    {"levels": [{"item": "Dansk", "level": 9}]},
    {"country": "Denmark"},
])
def test_an_answer_that_does_not_hold_is_refused_and_not_cached(asked, tmp_path, change):
    asked["answers"] = [_broken(**change)]
    with pytest.raises(cv_read.CvReadError):
        cv_read.read(MD)
    assert len(asked["calls"]) == 2  # asked once more
    assert not list((tmp_path / "cache").glob("*.json")) if (tmp_path / "cache").exists() else True


def test_levels_and_country_are_not_substrings(asked):
    assert cv_read.read(MD)["country"] == "dk"


def test_a_bad_first_answer_is_asked_once_more(asked):
    asked["answers"] = [_broken(email="x@y.com"), copy.deepcopy(READING)]
    assert cv_read.read(MD)["email"] == "mette.berg@example.com"
    assert len(asked["calls"]) == 2


def test_a_failed_call_is_a_cv_read_error_in_words(asked, tmp_path):
    asked["answers"] = [claude_cli.ClaudeError("no plan")]
    with pytest.raises(cv_read.CvReadError, match="no plan"):
        cv_read.read(MD)
    assert not (tmp_path / "cache").exists() or not list((tmp_path / "cache").glob("*"))


def test_a_second_read_of_the_same_cv_makes_no_call(asked):
    first = cv_read.read(MD)
    assert cv_read.read(MD) == first
    assert len(asked["calls"]) == 1


def test_line_endings_and_trailing_space_share_one_entry(asked):
    cv_read.read(MD)
    cv_read.read(MD.replace("\n", "\r\n") + "\n\n")
    assert len(asked["calls"]) == 1


def test_a_changed_cv_is_read_again(asked):
    cv_read.read(MD)
    asked["answers"] = [_broken(skills=["Python"])]
    assert cv_read.read(MD.replace("Docker", "Docker ")  + "\nMore")["skills"] == ["Python"]
    assert len(asked["calls"]) == 2


def test_a_new_prompt_version_is_asked_again(asked, monkeypatch):
    cv_read.read(MD)
    monkeypatch.setattr(cv_read, "PROMPT_VERSION", cv_read.PROMPT_VERSION + 1)
    cv_read.read(MD)
    assert len(asked["calls"]) == 2


def test_a_corrupt_cache_file_is_asked_again(asked, tmp_path):
    cv_read.read(MD)
    for f in (tmp_path / "cache").glob("*.json"):
        f.write_text("{not json", encoding="utf-8")
    cv_read.read(MD)
    assert len(asked["calls"]) == 2


def test_a_cached_answer_that_no_longer_holds_is_asked_again(asked, tmp_path):
    cv_read.read(MD)
    for f in (tmp_path / "cache").glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        data["answer"]["email"] = "gone@example.com"
        f.write_text(json.dumps(data), encoding="utf-8")
    assert cv_read.read(MD)["email"] == "mette.berg@example.com"
    assert len(asked["calls"]) == 2


def test_an_empty_cv_is_read_without_a_call(asked):
    reading = cv_read.read("  \n")
    assert reading["sections"] == [] and reading["skills"] == [] and asked["calls"] == []


def test_a_heading_with_a_kind_marker_still_matches(asked):
    md = MD.replace("## Kompetencer", "## Kompetencer <!-- kind: skills -->")
    assert cv_read.read(md)["sections"][2]["kind"] == "skills"


def test_the_recorded_answers_pass_the_check():
    """The spike's recorded Haiku readings (made-up CVs) are valid answers; the key is the prompt and input's hash."""
    from paths import TESTS_DIR

    folder = TESTS_DIR / "tailoring" / "fixtures" / "cv_reading" / "haiku" / "reader"
    files = sorted(folder.glob("*.json"))
    assert files
    keys = {hashlib.sha256((cv_read.PROMPT + "\0" + f"CV:\n<<<\n{md}\n>>>\n").encode()).hexdigest()[:12]: md
            for md in _recorded_cvs()}
    held = 0
    for f in files:
        rec = json.loads(f.read_text(encoding="utf-8"))
        md = keys.get(rec["key"])
        if md is not None:
            cv_read.check(rec["answer"], md)
            held += 1
    assert held, "no recorded answer matches the prompt: the prompt drifted from the recording"


def _recorded_cvs():
    import importlib.util

    from paths import REPO_ROOT

    spec = importlib.util.spec_from_file_location("record_cv_reading", REPO_ROOT / "scripts" / "record_cv_reading.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [c["md"] for c in module.build_reader_corpus().values()]


def test_section_kinds_of_a_column_are_among_the_reading_kinds():
    assert set(templates.SECTION_KINDS) <= set(cv_read.KINDS)
