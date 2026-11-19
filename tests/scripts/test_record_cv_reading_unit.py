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


# --- the facts check ---------------------------------------------------------------------------------------------

BODY = ('<h2>Erfaring</h2><div class="entry"><h3><span class="role">Analyst</span> | <span class="org">Acme</span>'
        '</h3><ul><li>Cut costs by 1,8 M kr in two  years.</li></ul></div>')


def test_a_quote_is_verbatim_when_the_body_reads_it_squashed():
    assert rcr.is_verbatim("Cut costs by 1,8 M kr in two years.", BODY)  # nbsp and a double space squashed
    assert rcr.is_verbatim("Analyst | Acme", BODY)
    assert not rcr.is_verbatim("Cut costs by 2 M kr", BODY)
    assert not rcr.is_verbatim("", BODY)


PLANTS = [{"kind": "number", "planted_value": "1,8 M kr", "quote": "Cut costs by 1,8 M kr"},
          {"kind": "employer", "planted_value": "Globex", "quote": "Globex"}]


def finding(kind, value, context):
    return {"kind": kind, "value": value, "context": context, "file": "cv"}


def test_a_plant_is_found_by_its_kind_and_value_or_its_quote():
    found = [finding("number", "1.8M kr", "Cut costs by 1,8 M kr in two years."), finding("employer", "Globex", "Analyst | Globex")]
    score = rcr.score_facts(PLANTS, found, BODY)
    assert score["per_kind"] == {"number": {"planted": 1, "found": 1}, "employer": {"planted": 1, "found": 1}}
    assert score["false_flags"] == 0 and score["verbatim"] == (1, 2)  # "Analyst | Globex" is not in the body


def test_the_right_value_under_the_wrong_kind_is_a_miss_and_a_false_flag():
    score = rcr.score_facts(PLANTS[1:], [finding("skill", "Globex", "Globex")], "Globex")
    assert score["per_kind"]["employer"] == {"planted": 1, "found": 0} and score["false_flags"] == 1


def test_a_flag_that_is_no_plant_is_a_false_flag_and_a_clean_body_has_only_those():
    score = rcr.score_facts([], [finding("skill", "SQL", "x"), finding("year", "2019", "y")], BODY)
    assert score["false_flags"] == 2 and score["per_kind"] == {}


def test_an_error_answer_finds_nothing():
    assert rcr.score_facts(PLANTS, {"error": "timeout"}, BODY)["per_kind"]["number"]["found"] == 0


def test_stability_is_the_share_of_bodies_with_the_same_flags_in_every_run_whatever_the_order():
    a, b = finding("skill", "SQL", "x"), finding("year", "2019", "y")
    same = {"c1": [[a, b], [b, a], [a, b]], "c2": [[], [], []]}
    assert rcr.stability(same) == 1.0
    differs = {"c1": [[a, b], [b], [a, b]], "c2": [[], [], []]}
    assert rcr.stability(differs) == 0.5


def facts_report(**changes):
    base = {"per_kind": {k: 0.95 for k in rcr.KINDS}, "false_clean_max": 1, "verbatim": 0.99, "stable": 0.96}
    base.update(changes)
    return base


def test_the_facts_verdict_follows_the_named_thresholds():
    assert rcr.facts_verdict(facts_report()) == "go"
    assert rcr.facts_verdict(facts_report(per_kind={**facts_report()["per_kind"], "skill": 0.89})) == "close"
    assert rcr.facts_verdict(facts_report(per_kind={**facts_report()["per_kind"], "skill": 0.9})) == "go"
    assert rcr.facts_verdict(facts_report(false_clean_max=2)) == "close"
    assert rcr.facts_verdict(facts_report(false_clean_max=3)) == "no-go"
    assert rcr.facts_verdict(facts_report(verbatim=0.97)) == "close"
    assert rcr.facts_verdict(facts_report(stable=0.94)) == "close"
    assert rcr.facts_verdict(facts_report(per_kind={**facts_report()["per_kind"], "degree": 0.79})) == "no-go"


def reader_report(**changes):
    base = {"sections": 1.0, "contacts": 0.99, "name": 1.0, "email": 1.0, "years": 0.95}
    base.update(changes)
    return base


def test_the_reader_verdict_follows_the_named_thresholds():
    assert rcr.reader_verdict(reader_report()) == "go"
    assert rcr.reader_verdict(reader_report(sections=0.97)) == "close"
    assert rcr.reader_verdict(reader_report(name=0.99)) == "close"
    assert rcr.reader_verdict(reader_report(years=0.94)) == "close"
    assert rcr.reader_verdict(reader_report(years=0.79)) == "no-go"
