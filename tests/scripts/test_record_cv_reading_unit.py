"""scripts/record_cv_reading.py: the spike of #429 measuring a model as a CV reader and a fact checker on made-up data.

Pure parts only: the scoring of an answer against what was built in, the corpus builders, the verdicts. The model
is never asked here; its recorded answers are read from `tests/tailoring/fixtures/cv_reading/recorded/`.
"""

import importlib.util

from paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("record_cv_reading", REPO_ROOT / "scripts" / "record_cv_reading.py")
rcr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rcr)

ENTRY = {"heading": "Analyst, Acme (2019 - 2024)", "role": "Analyst", "org": "Acme", "dates": "2019 - 2024",
         "place": None, "start_year": 2019, "end_year": 2024}
EXPECTED = {
    "name": "Anna Berg", "email": "anna.berg@example.com", "city": "Aarhus", "country": "dk",
    "working_languages": ["Danish", "English"],
    "sections": {"Erfaring": "experience", "Sprog": "languages"},
    "contacts": [{"kind": "phone", "label": "Tlf", "value": "+45 20 30 40 50"},
                 {"kind": "email", "label": None, "value": "anna.berg@example.com"}],
    "levels": {"Dansk": 5, "SQL": None},
    "entries": [ENTRY],
}


def answer(**changes):
    base = {
        "name": "Anna Berg", "email": "anna.berg@example.com", "city": "Aarhus", "country": "dk",
        "languages": [{"language": "Danish", "level": "native"}, {"language": "English", "level": "fluent"},
                      {"language": "French", "level": "basic"}],
        "sections": [{"heading": "Erfaring", "kind": "experience"}, {"heading": "Sprog", "kind": "languages"}],
        "contacts": [{"kind": "phone", "label": "Tlf", "value": "+45 20 30 40 50"},
                     {"kind": "email", "label": None, "value": "anna.berg@example.com"}],
        "levels": [{"item": "Dansk", "level": 5}, {"item": "SQL", "level": None}],
        "entries": [dict(ENTRY)],
    }
    base.update(changes)
    return base


def test_a_right_reading_scores_every_field_fully():
    score = rcr.score_reader(EXPECTED, answer())
    assert score and all(f["hit"] == f["total"] for f in score.values())
    assert score["sections"]["total"] == 2 and score["contacts"]["total"] == 2 and score["years"]["total"] == 2


def test_a_wrong_section_kind_is_a_miss_of_that_field_alone():
    wrong = answer(sections=[{"heading": "Erfaring", "kind": "education"}, {"heading": "Sprog", "kind": "languages"}])
    score = rcr.score_reader(EXPECTED, wrong)
    assert score["sections"] == {"hit": 1, "total": 2}
    assert score["name"] == {"hit": 1, "total": 1}


def test_name_and_email_must_be_exact():
    score = rcr.score_reader(EXPECTED, answer(name="Anna Berge", email="anna.berg@example.org"))
    assert score["name"]["hit"] == 0 and score["email"]["hit"] == 0


def test_a_year_off_by_one_misses_one_of_the_two():
    entry = {**ENTRY, "end_year": 2025}
    assert rcr.score_reader(EXPECTED, answer(entries=[entry]))["years"] == {"hit": 1, "total": 2}


def test_a_present_end_is_null_and_a_made_up_year_for_it_misses():
    expected = {**EXPECTED, "entries": [{**ENTRY, "end_year": None}]}
    assert rcr.score_reader(expected, answer(entries=[{**ENTRY, "end_year": None}]))["years"]["hit"] == 2
    assert rcr.score_reader(expected, answer(entries=[{**ENTRY, "end_year": 2025}]))["years"]["hit"] == 1


def test_heading_parts_are_scored_one_by_one_and_dashes_and_spaces_do_not_matter():
    entry = {**ENTRY, "org": "Acme A/S", "dates": "2019–2024", "place": "Aarhus"}
    score = rcr.score_reader(EXPECTED, answer(entries=[entry]))
    assert score["heading_role"]["hit"] == 1 and score["heading_org"]["hit"] == 0
    assert score["heading_dates"]["hit"] == 1 and score["heading_place"]["hit"] == 0


def test_a_contact_needs_its_kind_label_and_value():
    wrong = answer(contacts=[{"kind": "phone", "label": "Telefon", "value": "+45 20 30 40 50"},
                             {"kind": "email", "label": None, "value": "anna.berg@example.com"}])
    assert rcr.score_reader(EXPECTED, wrong)["contacts"] == {"hit": 1, "total": 2}


def test_a_level_is_never_guessed_for_a_word_outside_the_table():
    wrong = answer(levels=[{"item": "Dansk", "level": 5}, {"item": "SQL", "level": 4}])
    assert rcr.score_reader(EXPECTED, wrong)["levels"] == {"hit": 1, "total": 2}


def test_working_languages_are_the_set_at_native_fluent_or_working():
    assert rcr.score_reader(EXPECTED, answer())["languages"] == {"hit": 1, "total": 1}
    missing = answer(languages=[{"language": "Danish", "level": "native"}])
    assert rcr.score_reader(EXPECTED, missing)["languages"] == {"hit": 0, "total": 1}


def test_an_error_answer_misses_everything():
    score = rcr.score_reader(EXPECTED, {"error": "timeout"})
    assert score["name"] == {"hit": 0, "total": 1} and score["sections"] == {"hit": 0, "total": 2}
