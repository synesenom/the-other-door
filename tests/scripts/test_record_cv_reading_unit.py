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
    "working_languages": ["Dansk", "Engelsk"],
    "sections": {"Erfaring": "experience", "Sprog": "languages"},
    "contacts": [{"kind": "phone", "label": "Tlf", "value": "+45 00 00 00 00"},
                 {"kind": "email", "label": None, "value": "anna.berg@example.com"}],
    "levels": {"Dansk": 5, "SQL": None}, "skills": ["SQL", "Git"],
    "entries": [ENTRY],
}


def answer(**changes):
    base = {
        "name": "Anna Berg", "email": "anna.berg@example.com", "city": "Aarhus", "country": "dk",
        "languages": [{"language": "Dansk", "level": "native"}, {"language": "Engelsk", "level": "fluent"},
                      {"language": "Fransk", "level": "basic"}],
        "sections": [{"heading": "Erfaring", "kind": "experience"}, {"heading": "Sprog", "kind": "languages"}],
        "contacts": [{"kind": "phone", "label": "Tlf", "value": "+45 00 00 00 00"},
                     {"kind": "email", "label": None, "value": "anna.berg@example.com"}],
        "levels": [{"item": "Dansk", "level": 5}, {"item": "SQL", "level": None}], "skills": ["SQL", "git"],
        "entries": [dict(ENTRY)],
    }
    base.update(changes)
    return base


def test_a_right_reading_scores_every_field_fully():
    score = rcr.score_reader(EXPECTED, answer())
    assert score and all(f["hit"] == f["total"] for f in score.values())
    assert score["sections"]["total"] == 2 and score["contacts"]["total"] == 2 and score["years"]["total"] == 2
    assert score["skills"] == {"hit": 2, "total": 2}


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
    wrong = answer(contacts=[{"kind": "phone", "label": "Telefon", "value": "+45 00 00 00 00"},
                             {"kind": "email", "label": None, "value": "anna.berg@example.com"}])
    assert rcr.score_reader(EXPECTED, wrong)["contacts"] == {"hit": 1, "total": 2}


def test_a_level_is_never_guessed_for_a_word_outside_the_table():
    wrong = answer(levels=[{"item": "Dansk", "level": 5}, {"item": "SQL", "level": 4}])
    assert rcr.score_reader(EXPECTED, wrong)["levels"] == {"hit": 1, "total": 2}


def test_working_languages_are_the_set_at_native_fluent_or_working():
    assert rcr.score_reader(EXPECTED, answer())["languages"] == {"hit": 1, "total": 1}
    missing = answer(languages=[{"language": "Dansk", "level": "native"}])
    assert rcr.score_reader(EXPECTED, missing)["languages"] == {"hit": 0, "total": 1}


def test_an_error_answer_misses_everything():
    score = rcr.score_reader(EXPECTED, {"error": "timeout"})
    assert score["name"] == {"hit": 0, "total": 1} and score["sections"] == {"hit": 0, "total": 2}


def test_a_skill_the_reader_leaves_out_is_a_miss():
    assert rcr.score_reader(EXPECTED, answer(skills=["SQL"]))["skills"] == {"hit": 1, "total": 2}


def test_the_values_of_a_reading_are_counted_as_stretches_of_the_cv_but_for_the_country():
    md = "# Anna Berg\n\nTlf: +45 00 00 00 00\n\n## Sprog\n\n- Dansk: modersmål\n"
    ok = answer(name="Anna Berg", email=None, city=None, skills=[], contacts=[{"kind": "phone", "label": "Tlf", "value": "+45 00 00 00 00"}],
                languages=[{"language": "Dansk", "level": "native"}], sections=[{"heading": "Sprog", "kind": "languages"}],
                levels=[{"item": "Dansk", "level": 5}], entries=[])
    assert rcr.stretches(md, ok) == (6, 6)
    assert rcr.stretches(md, {**ok, "languages": [{"language": "Danish", "level": "native"}]}) == (5, 6)
    assert rcr.stretches(md, {"error": "x"}) == (0, 0)


# --- the facts check ---------------------------------------------------------------------------------------------

import json  # noqa: E402
import re  # noqa: E402

from door.render import html_doc  # noqa: E402

BODY = ('<h2>Erfaring</h2><div class="entry"><h3><span class="role">Analyst</span> | <span class="org">Acme</span>'
        '</h3><ul><li>Cut costs by 1,8 M kr in two  years.</li></ul></div>')
LETTER = "<p>I worked with Looker at Acme.</p>"


def test_a_quote_is_verbatim_when_one_body_reads_it_squashed():
    assert rcr.is_verbatim("Cut costs by 1,8 M kr in two years.", BODY)  # nbsp and a double space squashed
    assert rcr.is_verbatim("Analyst | Acme", BODY)
    assert rcr.is_verbatim("worked with Looker", BODY, LETTER)
    assert not rcr.is_verbatim("Cut costs by 2 M kr", BODY)
    assert not rcr.is_verbatim("", BODY)


PLANTS = [{"kind": "number", "planted_value": "1,8 M kr", "quote": "Cut costs by 1,8 M kr"},
          {"kind": "employer", "planted_value": "Globex", "quote": "Globex"}]


def finding(kind, value, context, file="cv"):
    return {"kind": kind, "value": value, "context": context, "file": file}


def test_a_plant_is_found_by_its_kind_and_value_or_its_quote():
    found = [finding("number", "1.8M kr", "Cut costs by 1,8 M kr in two years."), finding("employer", "Globex", "Analyst | Globex")]
    score = rcr.score_facts(PLANTS, found, BODY)
    assert score["per_kind"] == {"number": {"planted": 1, "found": 1}, "employer": {"planted": 1, "found": 1}}
    assert score["false_flags"] == 0 and score["verbatim"] == (1, 2)  # "Analyst | Globex" is not in the body


def test_the_right_value_under_the_wrong_kind_or_in_the_wrong_document_is_a_miss_and_a_false_flag():
    score = rcr.score_facts(PLANTS[1:], [finding("skill", "Globex", "Globex")], "Globex")
    assert score["per_kind"]["employer"] == {"planted": 1, "found": 0} and score["false_flags"] == 1
    letter_plant = [{**PLANTS[1], "file": "letter"}]
    assert rcr.score_facts(letter_plant, [finding("employer", "Globex", "Globex")], "Globex")["per_kind"]["employer"]["found"] == 0
    assert rcr.score_facts(letter_plant, [finding("employer", "Globex", "Globex", "letter")], "Globex")["per_kind"]["employer"]["found"] == 1


def test_a_flag_that_is_no_plant_is_a_false_flag_and_a_clean_body_has_only_those():
    score = rcr.score_facts([], [finding("skill", "SQL", "x"), finding("year", "2019", "y")], BODY)
    assert score["false_flags"] == 2 and score["per_kind"] == {}


def test_an_error_answer_finds_nothing():
    assert rcr.score_facts(PLANTS, {"error": "timeout"}, BODY)["per_kind"]["number"]["found"] == 0


def test_stability_is_the_share_of_cases_with_the_same_flags_in_every_run_whatever_the_order():
    a, b = finding("skill", "SQL", "x"), finding("year", "2019", "y")
    assert rcr.stability({"c1": [[a, b], [b, a], [a, b]], "c2": [[], [], []]}) == 1.0
    assert rcr.stability({"c1": [[a, b], [b], [a, b]], "c2": [[], [], []]}) == 0.5


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


# --- the made-up corpus ------------------------------------------------------------------------------------------

def test_every_expected_value_of_a_cv_is_a_literal_of_its_text():
    for person in rcr.PEOPLE[:15]:
        md, expected = rcr.render_cv_md(person)
        for field in ("name", "email", "city"):
            assert expected[field] in md, (person["name"], field)
        for heading in expected["sections"]:
            assert f"## {heading}\n" in md
        for c in expected["contacts"]:
            assert c["value"] in md and (c["label"] is None or c["label"] in md)
        for item in (*expected["levels"], *expected["skills"], *expected["working_languages"]):
            assert item in md
        for entry in expected["entries"]:
            assert f"### {entry['heading']}\n" in md
            for part in ("role", "org", "dates", "place"):
                assert entry[part] is None or entry[part] in entry["heading"]
            assert re.search(rf"\b{entry['start_year']}\b", entry["dates"])


def test_the_reader_corpus_has_twelve_cvs_in_three_languages_with_hard_headings_contacts_levels_and_dates():
    corpus = rcr.build_reader_corpus()
    assert len(corpus) >= 12 and len({c["lang"] for c in corpus.values()}) >= 3
    entries = [e for c in corpus.values() for e in c["expected"]["entries"]]
    assert len({re.sub(r"[^|,()–—-]", "", e["heading"])[:4] for e in entries}) >= 3
    assert any(e["end_year"] is None for e in entries)
    assert any(c["label"] is None for c in corpus.values() for c in c["expected"]["contacts"])
    assert any(v is None for c in corpus.values() for v in c["expected"]["levels"].values())
    dates = " ".join(e["dates"] for e in entries)
    for shape in (r"\b\d\d/\d{4}\b", r"\b\d{1,2}\.\d{1,2}\.\d{4}\b", r"\b\d{4}-\d\d\b"):
        assert re.search(shape, dates), shape
    assert re.search(r"\b\d{1,2}(st|nd|rd|th) [A-Z][a-z]+ \d{4}", " ".join(e["dates"] for p in rcr.PEOPLE if p["lang"] == "en"
                                                                           for e in rcr.render_cv_md(p)[1]["entries"]))


def test_a_person_can_be_written_in_another_language_keeping_names_employers_places_and_figures():
    person = next(p for p in rcr.PEOPLE if p["lang"] == "da")
    da, fr = rcr.render_cv_md(person)[0], rcr.render_cv_md(person, "fr")[0]
    assert da != fr and "## Erhvervserfaring" in da and "## Expérience professionnelle" in fr
    for kept in (person["name"], person["email"], person["jobs"][0]["org"], person["jobs"][0]["place"], "40 000"):
        assert (kept in da) == (kept in fr), kept


def test_at_least_half_of_the_bodies_are_in_another_language_than_their_source_and_half_the_planted_are_in_danish_or_french():
    corpus = rcr.build_body_corpus()
    planted = {k: v for k, v in corpus.items() if v["plants"]}
    clean = {k: v for k, v in corpus.items() if not v["plants"]}
    assert len(planted) >= 20 and len(clean) >= 5
    for part in (planted, clean):
        assert sum(v["lang"] != v["body_lang"] for v in part.values()) * 2 >= len(part)
    assert sum(v["body_lang"] in ("da", "fr") for v in planted.values()) * 2 >= len(planted)
    assert all(1 <= len(v["plants"]) <= 3 for v in planted.values())
    assert {p["kind"] for v in planted.values() for p in v["plants"]} == set(rcr.KINDS)
    for v in planted.values():
        assert all(rcr.is_verbatim(p["quote"], v["body"], v["letter"]) for p in v["plants"])


def test_a_body_is_what_a_tailor_makes_of_the_cv():
    person = rcr.PEOPLE[1]
    source, body = rcr.render_cv_md(person)[0], rcr.render_body(person, person["lang"])
    heads = html_doc.headings(body)
    assert len(heads) < len(re.findall(r"^## ", source, re.M))  # the interests are dropped
    text = html_doc.text(body)
    assert rcr._PACK[person["lang"]]["summary"].split(",")[0][:20] not in text  # a new summary
    assert len(re.findall(r"<h3>", body)) < len(re.findall(r"^### ", source, re.M))  # the oldest job and degree dropped
    assert heads.index(rcr._heads(person, person["lang"])["skills"]) < heads.index(rcr._heads(person, person["lang"])["experience"])  # reordered
    assert "; " in text  # two bullets merged


def test_a_skill_may_be_named_by_a_synonym_the_cv_backs():
    person = next(p for p in rcr.PEOPLE if "Power BI" in p["tools"] and not p["skill_levels"])
    assert "Power BI" in rcr.render_cv_md(person)[0] and "PowerBI" in rcr.render_cv_md(person, tailor=True)[0]


def test_numeric_and_day_month_dates_are_in_the_cvs_and_next_to_a_figure_in_the_bodies():
    for fmt, shape in (("mm/yyyy", r"\d\d/\d{4}"), ("d.m.yyyy", r"\d+\.\d+\.\d{4}"), ("yyyy-mm", r"\d{4}-\d\d")):
        person = next(p for p in rcr.PEOPLE if p["dfmt"] == fmt)
        text = html_doc.text(rcr.render_body(person, person["lang"]))
        assert re.search(rf"\d [^.]*\({shape}\)\.", text), fmt


def test_a_year_planted_in_a_numeric_date_is_found_in_that_date():
    person = next(p for p in rcr.PEOPLE if p["dfmt"] == "mm/yyyy" and p["lang"] == "fr")
    source, body = rcr.render_cv_md(person)[0], rcr.render_body(person, "fr")
    planted, info = rcr.plant(body, "year", person, "fr", 0, source)
    assert re.search(rf"\d\d/{info['planted_value']}", planted) and info["planted_value"] not in source


def test_some_cases_have_a_story_bank_and_some_a_letter_with_its_posting_and_the_claim_only_the_story_backs():
    corpus = rcr.build_body_corpus()
    story = [c for c in corpus.values() if c["story"]]
    letters = [c for c in corpus.values() if c["letter"]]
    assert story and letters and all(c["posting"] for c in letters) and not any(c["posting"] for c in corpus.values() if not c["letter"])
    for c in story:
        assert "4 000" in c["story"] and "dbt" in c["story"] and "**Context:**" in c["story"] and "**Result:**" in c["story"]
        assert "4 000" in html_doc.text(c["body"]) and "4 000" not in c["md"]
    for c in letters:
        assert "Looker" in c["posting"] and "Looker" in html_doc.text(c["letter"]) and "Looker" not in c["md"]
    assert any(p["file"] == "letter" for c in corpus.values() for p in c["plants"])


def test_planting_changes_one_place_and_says_what_was_planted():
    person = rcr.PEOPLE[1]
    source, body = rcr.render_cv_md(person)[0], rcr.render_body(person, "fr")
    for kind in rcr.KINDS:
        planted, info = rcr.plant(body, kind, person, "fr", 0, source)
        assert planted != body and info["kind"] == kind and rcr.is_verbatim(info["quote"], planted)
        assert info["planted_value"] not in source
    assert rcr.render_body(person, "fr") == body  # the original is not touched


def test_a_plant_with_no_place_to_stand_is_an_error():
    import pytest
    with pytest.raises(ValueError):
        rcr.plant("<p>nothing here</p>", "employer", rcr.PEOPLE[0], "en", 0, "")


def test_a_clean_body_may_hold_a_figure_written_another_way_that_the_cv_backs():
    corpus = rcr.build_body_corpus()
    person = rcr.PEOPLE[20]
    assert not corpus["b20-" + person["lang"] + "-" + corpus_lang(corpus, 20)]["plants"]
    assert rcr.render_body(person, rcr.body_lang(person), reformat=True) != rcr.render_body(person, rcr.body_lang(person))


def corpus_lang(corpus, n):
    return next(c["body_lang"] for k, c in corpus.items() if k.startswith(f"b{n:02d}-"))


def test_nothing_in_the_corpus_is_a_real_address_or_number():
    cases = [*rcr.build_reader_corpus().values(), *rcr.build_body_corpus().values()]
    for c in cases:
        for text in (c["md"], c.get("body", ""), c.get("letter", ""), c.get("story", ""), c.get("posting", "")):
            assert set(re.findall(r"@([\w.-]+\.\w+)", text)) <= {"example.com"}
            assert not re.search(r"\+\d\d \d\d [1-9]", text)


# --- recorded answers, the report and the baseline ---------------------------------------------------------------

def record(folder, case, run, corpus, task="facts", answer=None, error=None):
    folder.mkdir(parents=True, exist_ok=True)
    data = {"error": error} if error else {"key": rcr._key(task, corpus[case]), "answer": answer}
    (folder / f"{case}.{run}.json").write_text(json.dumps(data))


def test_recorded_answers_are_read_by_case_and_run_an_error_or_a_stale_record_is_a_miss(tmp_path):
    corpus = {"b00": {"md": "m", "story": "", "posting": "", "body": "b", "letter": "", "plants": []}}
    folder = tmp_path / "haiku" / "facts"
    record(folder, "b00", 0, corpus, answer=[finding("skill", "Rust", "Rust")])
    record(folder, "b00", 1, corpus, error="timeout")
    (folder / "b00.2.json").write_text(json.dumps({"key": "of-another-prompt", "answer": []}))
    got = rcr.load_recorded("haiku", "facts", corpus, root=tmp_path)["b00"]
    assert got[0] == [finding("skill", "Rust", "Rust")] and "error" in got[1] and "error" in got[2]
    assert rcr.load_recorded("sonnet", "facts", corpus, root=tmp_path) == {}
    assert rcr._recorded_ok(folder / "b00.0.json") and not rcr._recorded_ok(folder / "b00.1.json") and not rcr._recorded_ok(folder / "none.0.json")


def test_the_facts_report_counts_errors_as_misses_and_clean_bodies_apart():
    corpus = rcr.build_body_corpus()
    planted = next(n for n, c in corpus.items() if c["plants"] and not c["letter"])
    clean = next(n for n, c in corpus.items() if not c["plants"])
    perfect = [{"kind": p["kind"], "value": p["planted_value"], "context": p["quote"], "file": "cv"} for p in corpus[planted]["plants"]]
    noisy = [finding("skill", "Rust", "Rust"), finding("skill", "Go", "Go")]
    report = rcr.summarize("facts", {planted: [perfect, {"error": "x"}], clean: [noisy, noisy]}, corpus)
    kinds = {p["kind"] for p in corpus[planted]["plants"]}
    assert {k: report["per_kind"][k] for k in kinds} == {k: 0.5 for k in kinds}
    assert report["false_clean_max"] == 2 and report["stable"] == 0.5 and report["runs"] == 2 and report["calls"] == 4
    assert report["verdict"] == "no-go"
    assert f"| {sorted(kinds)[0]} | 50.0% |" in rcr.to_markdown("facts", report)


def test_the_reader_report_pools_the_fields_over_cases_and_runs_and_counts_stretches():
    corpus = rcr.build_reader_corpus()
    name = next(iter(corpus))
    report = rcr.summarize("reader", {name: [{"error": "x"}]}, corpus)
    assert report["fields"]["name"] == 0.0 and report["verdict"] == "no-go" and report["calls"] == 1


def test_the_baseline_fact_check_flags_what_the_rules_see_and_reads_the_story_bank_and_the_posting():
    corpus = rcr.build_body_corpus()
    name = next(n for n, c in corpus.items() if any(p["kind"] == "employer" for p in c["plants"]))
    assert any(f["kind"] == "employer" for f in rcr.baseline_facts(corpus[name]))
    clean = next(c for c in corpus.values() if c["letter"] and c["story"] and not c["plants"])
    assert not [f for f in rcr.baseline_facts(clean) if f["value"] in ("4 000", "dbt", "Looker", "120")]


# --- the prompts and the runner ----------------------------------------------------------------------------------

def test_a_record_names_the_prompt_and_input_it_answers():
    case = {"md": "m", "story": "", "posting": "", "body": "b", "letter": ""}
    assert rcr._key("facts", case) != rcr._key("facts", {**case, "body": "c"}) != rcr._key("reader", case)


def test_the_runner_records_each_case_once_and_asks_again_only_for_an_error(tmp_path, monkeypatch):
    calls = []

    def fake(task, model, case):
        calls.append(case["md"])
        return {"error": "timeout"} if len(calls) == 1 else [finding("skill", "Rust", "Rust")]

    def fake_ask(task, model, case):
        result = fake(task, model, case)
        if isinstance(result, dict):
            raise RuntimeError("timeout")
        return result

    monkeypatch.setattr(rcr, "ask_case", fake_ask)
    corpus = {n: {"md": n, "story": "", "posting": "", "body": "", "letter": "", "plants": []} for n in ("b00", "b01")}
    rcr.run("facts", "haiku", corpus, runs=1, root=tmp_path, workers=1)
    assert sorted(calls) == ["b00", "b01"]
    rcr.run("facts", "haiku", corpus, runs=1, root=tmp_path, workers=1)
    assert len(calls) == 3  # only the error is asked again
    assert all(isinstance(a[0], list) for a in rcr.load_recorded("haiku", "facts", corpus, root=tmp_path).values())


def test_the_prompts_name_what_the_corpus_is_hard_in():
    facts_prompt = rcr.PROMPTS["facts"]
    for word in ("STORY BANK", "POSTING", "COVER LETTER", "another language", "03/2019", "PowerBI"):
        assert word in facts_prompt
    assert "skills" in rcr.PROMPTS["reader"] and "as the CV writes it" in rcr.PROMPTS["reader"]


# --- what the committed answers say ------------------------------------------------------------------------------

def committed(model, task):
    corpus = rcr.build_reader_corpus() if task == "reader" else rcr.build_body_corpus()
    return rcr.summarize(task, rcr.load_recorded(model, task, corpus), corpus)


def test_every_committed_record_is_an_answer_to_the_prompt_and_input_of_today():
    for task, corpus in (("reader", rcr.build_reader_corpus()), ("facts", rcr.build_body_corpus())):
        for path in sorted((rcr.RECORDED).glob(f"*/{task}/*.json")):
            case = path.name.split(".")[0]
            assert rcr._recorded_ok(path, rcr._key(task, corpus[case])), path


def test_haiku_is_go_as_a_reader_and_a_fact_checker_on_the_harder_corpus():
    reader, check = committed("haiku", "reader"), committed("haiku", "facts")  # the reader: one run a case, recorded again with #430's prompt
    assert reader["verdict"] == "go" and reader["calls"] == 15 and reader["stretches"] == 1.0
    assert {f: round(v, 3) for f, v in reader["fields"].items() if v < 1} == {"levels": 0.987}
    assert check["verdict"] == "go" and check["calls"] == 84 and all(v == 1.0 for v in check["per_kind"].values())
    assert check["false_clean_max"] == 0 and round(check["verbatim"], 3) == 0.984 and check["stable"] == 1.0


def test_sonnet_is_close_on_the_facts_for_a_less_stable_check():
    check = committed("sonnet", "facts")  # its reader records went stale with #430's prompt and were not recorded again
    assert check["verdict"] == "close" and round(check["stable"], 3) == 0.857 and round(check["verbatim"], 3) == 0.993
    assert all(v == 1.0 for v in check["per_kind"].values()) and check["false_clean_max"] == 0


def test_the_fact_rules_of_today_are_no_go_on_the_same_cases():
    corpus = rcr.build_body_corpus()
    answers = {n: [rcr.baseline_facts(c)] for n, c in corpus.items()}
    assert rcr.summarize("facts", answers, corpus)["verdict"] == "no-go"


def test_no_record_is_an_error():
    assert all(rcr._recorded_ok(p) for p in rcr.RECORDED.glob("*/*/*.json"))


# --- the held-out corpus: other pools, the same mix --------------------------------------------------------------

def held():
    with rcr.held_out():
        return rcr.build_reader_corpus(), rcr.build_body_corpus()


def test_the_held_out_corpus_shares_no_name_employer_tool_degree_or_figure_with_the_tuned_one():
    tuned = [*rcr.build_reader_corpus().values(), *rcr.build_body_corpus().values()]
    held_reader, held_bodies = held()
    text = lambda cases: " ".join(c["md"] + c.get("body", "") + c.get("letter", "") + c.get("story", "") + c.get("posting", "") for c in cases)  # noqa: E731
    old, new = text(tuned), text([*held_reader.values(), *held_bodies.values()])
    with rcr.held_out():
        names = [p["name"] for p in rcr.PEOPLE]
        pools = [*rcr._ORGS, *rcr._TOOLS, *rcr._CERTS, *rcr._FAKE_ORGS, *rcr._FAKE_SKILLS, *rcr._FAKE_CERTS]
        figures = [a for lang in rcr._BULLETS.values() for _, a, _, f in lang for a in (a, f)]
    for name in names + pools + figures:
        assert name not in old, name
    for token in ("dbt", "Looker", "4 000", "120 countries", "Orchid", "Kubernetes"):
        assert token not in new, token
    assert set(rcr.PEOPLE[0]["name"].split()) & set(" ".join(names).split()) == set()  # the tuned corpus is restored afterwards


def test_the_held_out_corpus_has_the_same_mix_of_hard_cases():
    reader, bodies = held()
    assert len(reader) >= 12 and len(bodies) == 28
    planted = {k: v for k, v in bodies.items() if v["plants"]}
    assert {p["kind"] for v in planted.values() for p in v["plants"]} == set(rcr.KINDS)
    assert any(p["file"] == "letter" for v in planted.values() for p in v["plants"])
    assert sum(v["lang"] != v["body_lang"] for v in bodies.values()) * 2 >= len(bodies)
    assert sum(bool(v["story"]) for v in bodies.values()) >= 10 and sum(bool(v["letter"]) for v in bodies.values()) >= 5
    for v in planted.values():
        assert all(rcr.is_verbatim(p["quote"], v["body"], v["letter"]) for p in v["plants"])
    dates = " ".join(e["dates"] for c in reader.values() for e in c["expected"]["entries"])
    for shape in (r"\b\d\d/\d{4}\b", r"\b\d{1,2}\.\d{1,2}\.\d{4}\b", r"\b\d{4}-\d\d\b"):
        assert re.search(shape, dates), shape
    for c in reader.values():
        assert set(re.findall(r"@([\w.-]+\.\w+)", c["md"])) <= {"example.com"}


def held_committed(task):
    with rcr.held_out():
        corpus = rcr.build_reader_corpus() if task == "reader" else rcr.build_body_corpus()
        return rcr.summarize(task, rcr.load_recorded("haiku", task, corpus, rcr.RECORDED / "held-out"), corpus), corpus


def test_every_held_out_record_is_an_answer_to_the_prompt_and_input_of_today():
    for task in ("reader", "facts"):
        _, corpus = held_committed(task)
        paths = sorted((rcr.RECORDED / "held-out" / "haiku" / task).glob("*.json"))
        assert {p.name.split(".")[0] for p in paths} == set(corpus)  # the reader 1 run a case, the facts at least 1
        for path in paths:
            assert rcr._recorded_ok(path, rcr._key(task, corpus[path.name.split(".")[0]])), path


def test_haiku_is_go_on_the_held_out_corpus_the_prompts_never_saw():
    reader, _ = held_committed("reader")
    facts, _ = held_committed("facts")
    assert (reader["verdict"], facts["verdict"]) == ("go", "go")
