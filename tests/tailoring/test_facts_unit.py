"""Unit tests for tailoring/facts.py: the offline check of a tailored CV and letter (HTML bodies) against cv.md."""

import json

import pytest

from door.tailoring import facts

CV_MD = "### Senior Dev | Acme A/S - 2019 - present\n- Cut churn by 38% in 2021. Team of 12. Raised 1,200 leads.\n"


def _bad(tex, cv_md=CV_MD, file="cv", letter_sources=None, **kw):
    claims = facts.extract_claims(tex, file)
    return facts.unsupported(claims, [cv_md], letter_sources, current_year=kw.get("current_year", 2026))


def _values(tex, **kw):
    return sorted(c["value"] for c in _bad(tex, **kw))


# --- numbers and years -------------------------------------------------------

def test_invented_percentage_is_flagged_with_context():
    out = _bad(r"<li>Cut churn by 40% in 2021</li>")
    assert [(c["kind"], c["value"], c["file"]) for c in out] == [("number", "40%", "cv")]
    assert "Cut churn by 40%" in out[0]["context"]


def test_supported_figures_are_clean():
    assert _bad(r"<li>Cut churn by 40% in 2021</li>", cv_md="40 % churn cut, 2021") == []


def test_single_digits_and_embedded_digits_are_not_tokens():
    assert _bad(r"<li>Led 5 people, used Python3, since 2015 team</li>", cv_md="2015") == []


def test_thousand_separators_and_decimal_comma():
    assert _bad(r"<li>Raised 1.200 leads</li>", cv_md="1,200 leads") == []
    assert _bad(r"<li>Score 3,5 of it</li>", cv_md="rated 3.5 here") == []
    assert _values(r"<li>Raised 1,300 leads</li>") == ["1300"]


def test_two_digit_number_is_claimed_single_is_not():
    assert _values(r"<li>Team of 10 and 3 others</li>") == ["10"]


def test_current_year_is_skipped():
    assert _values(r"<li>Since 2026 and 2024</li>") == ["2024"]


def test_percent_claim_passes_against_bare_number():
    assert _bad(r"<li>Cut by 38%</li>", cv_md="reduced by 38 points") == []


def test_percent_strict_otherwise():
    assert _values(r"<li>Cut by 40%</li>") == ["40%"]


@pytest.mark.parametrize("html", [
    '<header class="cv-header"><h1>Jane</h1><p class="contact"><span>+45 12 34 56 78</span><span>j@x.com</span><span><a href="https://x.com/77">x.com/77</a></span><span>Copenhagen 2100</span></p></header>',
    '<header class="letter-header"><h1>Jane</h1><p class="contact"><span>+45 12 34 56 78</span><span>Aarhus 8000</span></p></header>',
    '<div class="recipient"><p>Hiring team 5500</p><p>Acme 9000</p><p>Odense 5000</p></div>',
    '<div class="closing"><p class="signoff">Regards</p><p><strong>X 7777</strong></p></div>',
    '<p class="date">11. oktober 2026 - 8888</p>',
    '<p><a href="https://x.com/a/2024">text</a></p>',
    "line one<br>two",
    "<!-- Keywords: 99 and 98 -->\n<!-- Tailoring: 97 of 96 -->",
])
def test_what_is_not_content_makes_no_claims(html):
    assert facts.extract_claims(html, "cv") == []


def test_a_percent_sign_is_text():
    assert _values(r"<li>Up 40% year</li>") == ["40%"]


# --- employers ----------------------------------------------------------------

EMP = '<div class="entry"><h3>Senior Dev | Acme A/S &mdash; 2019 &ndash; present</h3><ul><li>x</li></ul></div>'


def test_employer_in_cv_md_is_clean():
    assert _bad(EMP) == []


def test_employer_not_in_cv_md_is_flagged():
    out = _bad(EMP, cv_md="### Dev | Other - 2019 - 2020")
    assert [(c["kind"], c["value"]) for c in out if c["kind"] == "employer"] == [("employer", "Acme A/S")]


def test_employer_match_is_case_space_and_ampersand_insensitive():
    tex = r"<div class=entry><h3>Dev | acme  &amp; sons --- 2019 -- 2020</h3></div>"
    assert _bad(tex, cv_md="Dev | ACME & Sons - 2019 - 2020") == []


def test_heading_without_pipe_is_skipped():
    assert _bad(r"<div class=entry><h3>Freelance --- 2019 -- 2020</h3></div>", cv_md="2019 2020") == []


def test_letter_employers_not_checked():
    assert _bad(r"I worked at Zeta Corp <div class=entry><h3>A | Zeta --- 2019</h3></div>", file="cover_letter") == []


def test_letter_number_supported_by_posting_but_cv_number_not():
    letter = _bad(r"We grew 77% last year", file="cover_letter", letter_sources=[CV_MD, "grew 77% last year"])
    assert letter == []
    cv = facts.unsupported(facts.extract_claims(r"<li>We grew 77%</li>", "cv"), [CV_MD], ["77%"], current_year=2026)
    assert [c["value"] for c in cv] == ["77%"]


def test_year_range_dash_forms():
    tex = r"<div class=entry><h3>A | Acme A/S --- 2018--2020</h3></div>"
    assert _bad(tex, cv_md="Acme A/S 2018 - 2020") == []
    out = _bad(tex, cv_md="Acme A/S 2018 - 2019")
    assert [(c["kind"], c["value"]) for c in out] == [("year", "2020")]


def test_dedup():
    assert len(_bad(r"<li>77% up</li>" "\n" r"<li>77% up</li>")) == 1


# --- skills, tools, certifications and degrees (#369) -------------------------

TERM_CV_MD = """\
## Education
### MSc in Computer Science | DTU - 2016
## Skills
Python, Kubernetes, SQL, SAP S/4HANA
## Certifications
- **Certified Kubernetes Administrator (CKA)** - 2020
"""


def _terms(tex, cv_md=TERM_CV_MD, file="cv", aliases=None, letter_sources=None):
    claims = facts.extract_claims(tex, file)
    out = facts.unsupported(claims, [cv_md], letter_sources, current_year=2026, aliases=aliases)
    return [(c["kind"], c["value"]) for c in out if c["kind"] in ("skill", "certification", "degree")]


@pytest.mark.parametrize("a,b", [
    ("Python", "python"), ("Kubernetes", "kubernetes."), ("Data Pipelines", "data pipeline"),
    ("Power-BI", "power bi"), ("Excel (advanced)", "excel advanced"),
])
def test_term_key_folds_case_punctuation_and_plural(a, b):
    assert facts._term_key(a) == facts._term_key(b)


@pytest.mark.parametrize("a,b", [("C++", "C"), ("C#", "C"), (".NET", "NET"), ("S/4HANA", "S4HANA")])
def test_term_key_keeps_technical_symbols_distinct(a, b):
    assert facts._term_key(a) != facts._term_key(b)


def test_skills_section_items_are_claims():
    tex = "<h2>Skills</h2><p>Python, Terraform; SQL</p>\n<h2>Languages</h2><p>English</p>\n"
    claims = [c for c in facts.extract_claims(tex, "cv") if c["kind"] == "skill"]
    assert [c["value"] for c in claims] == ["Python", "Terraform", "SQL"]
    assert "Terraform" in claims[1]["context"]


def test_html_line_breaks_stay_out_of_skill_values():
    tex = "<h2>Skills</h2><p>Python, SQL <br>REST APIs <br>Docker</p>\n"
    claims = [c for c in facts.extract_claims(tex, "cv") if c["kind"] == "skill"]
    assert [c["value"] for c in claims] == ["Python", "SQL", "REST APIs", "Docker"]


def test_invented_skill_in_skills_section_is_flagged_once():
    assert _terms("<h2>Skills</h2>\n<li>Python, Terraform</li>\n") == [("skill", "Terraform")]


def test_danish_skills_heading_is_read():
    assert _terms("<h2>Kompetencer</h2><p>Python, Terraform</p>\n") == [("skill", "Terraform")]


def test_section_title_itself_is_no_claim():
    assert _terms("<h2>Skills</h2>\n<h2>Certifications</h2>\n") == []


def test_bullets_claim_technical_tokens_only():
    tex = "<li>Led the Terraform rollout with Kubernetes, CI/CD and Node.js; cut cost</li>\n"
    assert _terms(tex) == [("skill", "CI/CD"), ("skill", "Node.js")]


def test_plain_words_in_bullets_are_not_claims():
    assert _terms("<li>Led the team and improved communication with Leadership</li>\n") == []


@pytest.mark.parametrize("word", ["communication", "Leadership", "January", "Monday", "Kommunikation"])
def test_stop_list_words_are_never_claimed(word):
    assert _terms(f"<h2>Skills</h2><p>Python, {word}</p>") == []


def test_abbreviations_urls_and_emails_are_not_technical():
    assert _terms("<li>E.g. Ph.D. work, i.e. and/or 24/7 via jane.doe@example.com www.x.com A/S</li>\n") == []


def test_certification_not_in_sources_is_flagged():
    tex = "<h2>Certifications</h2>\n<li>AWS Certified Solutions Architect --- 2022</li>\n"
    assert _terms(tex) == [("certification", "AWS Certified Solutions Architect")]


def test_supported_certification_is_clean():
    tex = "<h2>Certifications and licences</h2>\n<li>Certified Kubernetes Administrator (CKA) --- 2020</li>\n"
    assert _terms(tex) == []


def test_degree_not_in_sources_is_flagged():
    tex = "<h2>Education</h2>\n<div class=entry><h3>PhD in Quantum Gravity | DTU --- 2016</h3></div>\n"
    assert _terms(tex) == [("degree", "PhD in Quantum Gravity")]


def test_degree_phrase_or_reworded_level_and_field_is_supported():
    assert _terms("<h2>Education</h2>\n<li>MSc Computer Science, DTU, 2016</li>\n") == []
    assert _terms("<h2>Education</h2>\n<li>MSc in Computer Science | DTU --- 2016</li>\n") == []


def test_education_year_only_lines_are_ignored():
    assert _terms("<h2>Education</h2><p>2016</p>\n") == []


def test_alias_makes_an_abbreviation_supported_both_ways():
    aliases = {"k8s": "Kubernetes"}
    assert _terms("<h2>Skills</h2><p>k8s</p>\n", aliases=aliases) == []
    assert _terms("<h2>Skills</h2><p>Kubernetes</p>\n", cv_md="k8s everywhere", aliases=aliases) == []
    assert _terms("<h2>Skills</h2><p>k8s</p>\n", aliases={}) == [("skill", "k8s")]


def test_alias_null_means_not_a_skill():
    assert _terms("<h2>Skills</h2><p>Python, Teamwork</p>\n", aliases={"teamwork": None}) == []


def test_partial_name_of_a_source_skill_is_supported():
    assert _terms("<h2>Skills</h2><p>SAP S/4HANA</p>\n") == []
    assert _terms("<h2>Skills</h2><p>SAP S/4HANA, S/4HANA</p>\n", cv_md="SAP S/4HANA") == []


def test_case_and_plural_differences_are_supported():
    assert _terms("<h2>Skills</h2><p>python, Kubernetes, sql</p>\n") == []
    assert _terms("<h2>Skills</h2><p>SQL queries</p>\n", cv_md="SQL query tuning") == []


def test_skill_label_before_a_colon_is_dropped():
    assert _terms("<h2>Skills</h2>\n<strong>Languages:</strong> Python, SQL\n") == []


def test_letter_echo_of_the_ad_is_supported_but_the_cv_is_flagged():
    letter = "We use CI/CD daily."
    assert _terms(letter, file="cover_letter", letter_sources=[TERM_CV_MD, "CI/CD pipelines"]) == []
    assert _terms(letter, file="cover_letter") == [("skill", "CI/CD")]
    assert _terms("<h2>Skills</h2><p>CI/CD</p>\n", letter_sources=[TERM_CV_MD, "CI/CD"]) == [("skill", "CI/CD")]


def test_duplicate_term_claims_are_deduplicated():
    tex = "<h2>Skills</h2><p>Terraform, Terraform</p>\n"
    assert _terms(tex) == [("skill", "Terraform")]


def test_without_aliases_argument_old_calls_still_work():
    claims = facts.extract_claims("<li>Cut churn by 38% in 2021</li>", "cv")
    assert facts.unsupported(claims, [CV_MD], current_year=2026) == []


# --- check / load ---------------------------------------------------------------

@pytest.fixture
def dirs(tmp_path):
    out, prof = tmp_path / "out", tmp_path / "profile"
    out.mkdir(), prof.mkdir()
    (prof / "cv.md").write_text(CV_MD, encoding="utf-8")
    (out / "cv.html").write_text(r"<li>Cut churn by 38% in 2021</li>", encoding="utf-8")
    (out / "cover_letter.html").write_text("Hello", encoding="utf-8")
    return out, prof


def test_check_invented_writes_facts_json(dirs):
    out, prof = dirs
    (out / "cv.html").write_text(r"<li>Cut churn by 97%</li>", encoding="utf-8")
    found = facts.check(out, prof)
    assert [c["value"] for c in found] == ["97%"]
    data = json.loads((out / "facts.json").read_text())
    assert data["unsupported"] == found and data["checked_at"]
    assert facts.load(out) == found


def test_check_clean_writes_empty(dirs):
    out, prof = dirs
    assert facts.check(out, prof) == []
    assert json.loads((out / "facts.json").read_text())["unsupported"] == []


def test_check_write_false_writes_nothing(dirs):
    out, prof = dirs
    assert facts.check(out, prof, write=False) == []
    assert not (out / "facts.json").exists()


def test_check_unknown_without_cv_md_or_cv_tex(dirs):
    out, prof = dirs
    (prof / "cv.md").unlink()
    assert facts.check(out, prof) is None
    assert not (out / "facts.json").exists()
    (prof / "cv.md").write_text(CV_MD)
    (out / "cv.html").unlink()
    assert facts.check(out, prof) is None


def test_corrupt_posting_json_tolerated(dirs):
    out, prof = dirs
    (out / "posting.json").write_text("{nope")
    assert facts.check(out, prof) == []


def test_story_bank_figure_is_supported(dirs):
    out, prof = dirs
    (out / "cv.html").write_text(r"<li>Saved 4,500 hours</li>", encoding="utf-8")
    assert [c["value"] for c in facts.check(out, prof)] == ["4500"]
    (prof / "story_bank.md").write_text("Saved 4500 hours.")
    assert facts.check(out, prof) == []


def test_carl_story_figure_in_any_field_is_supported(dirs):
    out, prof = dirs
    (out / "cv.html").write_text(r"<li>Saved 4,500 hours and 7300 euros</li>", encoding="utf-8")
    (prof / "story_bank.md").write_text(
        "## Saved time\n\n**Context**: Reports took long.\n**Action**: Automated them.\n"
        "**Result**: Saved 4500 hours.\n**Learning**: It cost 7300 euros to learn.\n"
    )
    assert facts.check(out, prof) == []


def test_load_missing_or_corrupt(tmp_path):
    assert facts.load(tmp_path) is None
    (tmp_path / "facts.json").write_text("{nope")
    assert facts.load(tmp_path) is None


def test_no_model_call(dirs, monkeypatch):
    import subprocess
    from door.core import claude_cli

    def boom(*a, **k):
        raise AssertionError("model called")
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(claude_cli, "ask", boom)
    monkeypatch.setattr(claude_cli, "run", boom)
    out, prof = dirs
    assert facts.check(out, prof) == []


def test_check_applies_the_alias_file_and_never_rewrites_it(dirs, tmp_path, monkeypatch):
    from door.core import workspace

    out, prof = dirs
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs)
    (prof / "cv.md").write_text(CV_MD + "Kubernetes\n")
    (out / "cv.html").write_text("<h2>Skills</h2><p>k8s, Looker</p>\n", encoding="utf-8")
    assert [(c["kind"], c["value"]) for c in facts.check(out, prof)] == [("skill", "k8s"), ("skill", "Looker")]
    body = '{"k8s": "Kubernetes", "looker": null}'
    (jobs / "skill_aliases.json").write_text(body)
    assert facts.check(out, prof) == []
    assert (jobs / "skill_aliases.json").read_text() == body


def test_check_tolerates_a_corrupt_alias_file(dirs, tmp_path, monkeypatch):
    from door.core import workspace

    out, prof = dirs
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs)
    (jobs / "skill_aliases.json").write_text("{nope")
    (out / "cv.html").write_text("<h2>Skills</h2><p>Terraform</p>\n", encoding="utf-8")
    found = facts.check(out, prof)
    assert [(c["kind"], c["value"], c["file"]) for c in found] == [("skill", "Terraform", "cv")]
    assert set(found[0]) == {"kind", "value", "context", "file"}
    assert (jobs / "skill_aliases.json").read_text() == "{nope"


def test_check_letter_may_echo_the_ad_skills_but_the_cv_may_not(dirs):
    out, prof = dirs
    (out / "posting.json").write_text(json.dumps({"title": "Dev", "description": "You know CI/CD and Terraform."}))
    (out / "cover_letter.html").write_text("I have used CI/CD at scale.", encoding="utf-8")
    assert facts.check(out, prof) == []
    (out / "cv.html").write_text("<h2>Skills</h2><p>Terraform</p>\n", encoding="utf-8")
    assert [c["value"] for c in facts.check(out, prof)] == ["Terraform"]


# --- amounts with a suffix ---------------------------------------------------

@pytest.mark.parametrize("tex", [r"<li>3x faster builds</li>", r"<li>Saved 40k a year</li>", r"<li>Raised €3M</li>",
                                 r"<li>A 2.5m budget</li>", r"<li>50M users</li>"])
def test_invented_suffixed_amount_is_flagged(tex):
    assert len(_bad(tex)) == 1


def test_suffixed_amount_matches_its_spelled_out_source():
    assert _bad(r"<li>Saved 40k and 2.5M</li>", cv_md="Saved 40,000 and 2,500,000 a year") == []
    assert _bad(r"<li>Saved 40,000</li>", cv_md="Saved 40k a year") == []
    assert _bad(r"<li>3x faster</li>", cv_md="made builds 3x faster") == []


def test_units_glued_to_a_number_are_not_amounts():
    assert _bad(r"<li>Carried 40kg and ran 10km</li>") == []


def test_list_tags_are_not_certifications():
    tex = "<h2>Certifications</h2>\n<ul>\n<li>CMA --- 2019</li>\n</ul>\n"
    assert [c["value"] for c in facts.extract_claims(tex, "cv") if c["kind"] != "year"] == ["CMA"]


def test_document_and_country_acronyms_are_not_skills():
    assert _terms("<li>Hello CV, PDF and KPI in the EU and DKK</li>\n") == []


# --- French (#389) -------------------------------------------------------------

FR_MD = (
    "### Directeur des ventes | Acme SAS - octobre 2019 - présent\n"
    "- Salaire cible 45 000 €. Plus de 2,5 ans de pilotage. Pris en charge 1 200 comptes.\n"
    "- En ligne depuis octobre 2026.\n"
)


@pytest.mark.parametrize("sep", [" ", "\u00a0", "\u202f"])
def test_french_thousands_separators_are_one_figure(sep):
    assert _bad(rf"<li>Salaire cible 45{sep}000 €</li>", cv_md=FR_MD) == []
    assert _bad(rf"<li>Pris en charge 1{sep}200 comptes</li>", cv_md=FR_MD) == []


def test_french_figure_absent_from_cv_md_is_one_entry():
    out = _bad(r"<li>Salaire cible 60 000 €</li>", cv_md=FR_MD)
    assert [(c["kind"], c["value"]) for c in out] == [("number", "60000")]


def test_french_figure_spelled_without_a_separator_matches_the_spaced_source():
    assert _bad(r"<li>Salaire cible 45000 €</li>", cv_md=FR_MD) == []
    assert _bad(r"<li>Salaire cible 45,0</li>", cv_md="45,0") == []


def test_french_decimal_comma_and_k_euro():
    assert _bad(r"<li>Plus de 2,5 ans de pilotage</li>", cv_md=FR_MD) == []
    assert _bad(r"<li>Salaire cible 45 k€</li>", cv_md=FR_MD) == []
    assert _bad(r"<li>Salaire cible 45K€</li>", cv_md=FR_MD) == []
    assert _values(r"<li>Salaire cible 50 k€</li>", cv_md=FR_MD) == ["50000"]


def test_french_month_dates_are_not_figures():
    tex = r"<li>Acme, octobre 2019 -- présent. En ligne depuis oct. 2026, puis 10/2026, le 29 octobre 2026</li>"
    # no day or month number is claimed; only years can be
    assert _values(tex, cv_md="", current_year=2025) == ["2019", "2026"]
    assert _bad(tex, cv_md=FR_MD, current_year=2026) == []


def test_french_letter_date_line_needs_no_source():
    tex = "<p>Paris, le 29 octobre 2026<br>Objet : candidature</p>"
    assert _bad(tex, file="cover_letter", current_year=2026) == []
    assert _values("Paris, le 29 octobre 2024", file="cover_letter", cv_md="") == ["2024"]


def test_a_french_cv_with_everything_present_is_clean():
    tex = (
        "<h2>Expérience professionnelle</h2>\n"
        "<div class=entry><h3>Directeur des ventes | Acme SAS &mdash; octobre 2019 &ndash; présent</h3><ul>\n"
        "<li>Salaire cible 45\u202f000\u00a0€, plus de 2,5 ans de pilotage, 1\u202f200 comptes</li>\n"
        "</ul></div>\n"
    )
    assert _bad(tex, cv_md=FR_MD, current_year=2026) == []


# --- a CV's unfilled gaps ----------------------------------------------------

_TODO_CV = "Phone: TODO\nMSc, Aarhus University, TODO\n"


def _todos(tex, **kw):
    return [c for c in _bad(tex, cv_md=_TODO_CV, **kw) if c["kind"] == "placeholder"]


def test_a_todo_in_the_body_is_flagged_though_the_cv_has_it_too():
    found = _todos("<p>MSc, Aarhus University, TODO</p>")
    assert [(c["value"], c["file"]) for c in found] == [("TODO", "cv")]
    assert "Aarhus" in found[0]["context"]


def test_a_todo_in_a_header_argument_is_flagged():
    assert _todos('<header class="cv-header"><h1>Ada</h1><p class="contact"><span>TODO</span><span>ada@x.org</span></p></header>')


def test_a_todo_in_the_letter_is_flagged():
    assert _todos("<p>Call me on TODO.</p>", file="cover_letter")


def test_a_todo_is_reported_once_not_also_as_a_skill():
    assert len(_bad("<p>Phone: TODO</p>", cv_md="Phone: 12345\n")) == 1


@pytest.mark.parametrize("tex", [
    "<p>MASTODON and TODOS</p>",
    "<!-- Tailoring: TODO tighten this -->\n<p>Fine.</p>",
])
def test_not_a_gap_in_the_document(tex):
    assert _todos(tex) == []


# --- UK dates (#600) ---------------------------------------------------------


def test_uk_numeric_and_written_dates_claim_only_the_year():
    # the day and month are never figures; the year is, in either form
    for text in ("Started 03/11/2026", "Started 13 November 2026", "Started 13th Nov. 2026", "Started 13/11/2026"):
        assert _values(text, cv_md="", current_year=2025) == ["2026"], text


def test_same_date_in_another_form_is_backed_for_a_uk_cv():
    cv_md = "### Engineer | Acme Ltd - 13 November 2026 - present\n"
    for tex in ("Joined 13/11/2026", "Joined 13 November 2026", "Joined 13 Nov 2026"):
        assert _bad(tex, cv_md=cv_md, current_year=2025) == [], tex


def test_day_month_ordering_does_not_change_the_claims():
    # 03/11/2026 and 11/03/2026 both reduce to the year, so the ordering cannot make a claim unbacked
    assert _values("03/11/2026", cv_md="", current_year=2025) == _values("11/03/2026", cv_md="", current_year=2025)


# --- company forms are not skills ---------------------------------------------

@pytest.mark.parametrize("form", ["ApS", "GmbH", "SARL", "AB", "Ltd", "S.A.S.", "Kft."])
def test_company_form_is_not_a_skill(form):
    tex = f"<h2>Skills</h2><p>Python, {form}</p><h2>Experience</h2><ul><li>Analyst at Example {form}.</li></ul>"
    assert "ApS" not in _values(tex, cv_md="Python")
    values = _values(tex, cv_md="Python")
    assert all(v.strip(".").casefold() != form.strip(".").casefold() for v in values)


def test_real_skill_and_suffix_word_phrase_still_flag():
    tex = "<h2>Skills</h2><p>PostgreSQL, AB testing</p>\n"
    assert _values(tex, cv_md="Python") == ["AB testing", "PostgreSQL"]


# --- reasons recorded by the tailor ---------------------------------------------

def _setup(tmp_path, tex=r"<li>Cut churn by 40% in 2021 and TODO</li>"):
    out, prof = tmp_path / "out", tmp_path / "prof"
    out.mkdir(parents=True)
    prof.mkdir()
    (prof / "cv.md").write_text(CV_MD, encoding="utf-8")
    (out / "cv.html").write_text(tex + "\n", encoding="utf-8")
    return out, prof


def _keep(**kw):
    return {"value": "40%", "kind": "number", "file": "cv", "reason": "from the ad", **kw}


def test_keep_writes_reason_and_load_returns_it(tmp_path):
    out, prof = _setup(tmp_path)
    facts.check(out, prof, keep=[_keep()])
    item = next(i for i in facts.load(out) if i["value"] == "40%")
    assert item["reason"] == "from the ad"
    todo = next(i for i in facts.load(out) if i["kind"] == "placeholder")
    assert "reason" not in todo


def test_reason_is_kept_on_rerun_while_flagged_and_dropped_when_not(tmp_path):
    out, prof = _setup(tmp_path)
    facts.check(out, prof, keep=[_keep()])
    facts.check(out, prof)
    assert next(i for i in facts.load(out) if i["value"] == "40%")["reason"] == "from the ad"
    (out / "cv.html").write_text("<li>Team of 12</li>\n", encoding="utf-8")
    facts.check(out, prof)
    assert facts.load(out) == []


def test_keep_for_unflagged_item_and_placeholder_is_ignored(tmp_path):
    out, prof = _setup(tmp_path)
    facts.check(out, prof, keep=[_keep(value="99%"), _keep(value="TODO", kind="placeholder")])
    assert all("reason" not in i for i in facts.load(out))


def test_reason_is_cleaned(tmp_path):
    out, prof = _setup(tmp_path)
    facts.check(out, prof, keep=[_keep(reason="a\n\tb\x07" + "x" * 300)])
    reason = next(i for i in facts.load(out) if i["value"] == "40%")["reason"]
    assert len(reason) == 200 and reason.startswith("a b") and "\n" not in reason and "\x07" not in reason
    out2, prof2 = _setup(tmp_path / "b")
    facts.check(out2, prof2, keep=[_keep(reason=5)])
    assert "reason" not in next(i for i in facts.load(out2) if i["value"] == "40%")


def test_write_false_merges_saved_reasons_without_writing(tmp_path):
    out, prof = _setup(tmp_path)
    facts.check(out, prof, keep=[_keep()])
    before = (out / "facts.json").read_text(encoding="utf-8")
    found = facts.check(out, prof, write=False)
    assert next(i for i in found if i["value"] == "40%")["reason"] == "from the ad"
    assert (out / "facts.json").read_text(encoding="utf-8") == before
