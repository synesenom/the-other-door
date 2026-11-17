"""Unit tests for tailoring/readability.py: the ATS read-back of a compiled PDF. Offline."""

import pytest

from door.tailoring import readability
from pdf_utils import make_pdf

NAME = "Jane Doe"
HEADINGS = ["Profile", "Experience", "Skills & Tools"]
GOOD = (
    "Jane Doe\nSenior data engineer with many years of building pipelines.\n"
    "Profile\nI build data platforms in Python and SQL.\n"
    "Experience\nAcme: led a team that shipped Airflow jobs.\n"
    "Skills & Tools\nPython, SQL, Airflow, dbt\n"
)


def kinds(found):
    return [p["kind"] for p in found]


def test_clean_text_has_no_problems():
    assert readability.problems(GOOD, name=NAME, headings=HEADINGS, keywords=["Python", "Airflow"]) == []


def test_missing_name():
    found = readability.problems(GOOD.replace("Jane Doe", "J. D."), name=NAME, headings=[], keywords=[])
    assert kinds(found) == ["missing"] and "Jane Doe" in found[0]["detail"]


def test_missing_heading():
    found = readability.problems(GOOD.replace("Experience\n", ""), name=NAME, headings=HEADINGS, keywords=[])
    assert kinds(found) == ["missing"] and "Experience" in found[0]["detail"]


def test_headings_out_of_order():
    text = "Jane Doe\nExperience\nwork " * 10 + "\nProfile\nabout me\nSkills & Tools\nPython\n"
    found = readability.problems(text, name=NAME, headings=HEADINGS, keywords=[])
    assert "order" in kinds(found)


def test_heading_glued_to_text():
    text = GOOD.replace("Experience\nAcme", "Experience Acme")
    found = readability.problems(text, name=NAME, headings=HEADINGS, keywords=[])
    assert kinds(found) == ["glued"] and "Experience" in found[0]["detail"]


def test_garbled_replacement_and_private_use_glyphs():
    for bad in ("�", ""):
        found = readability.problems(GOOD + "Tools " + bad + "\n", name=NAME, headings=[], keywords=[])
        assert "garbled" in kinds(found)


def test_empty_page_text():
    found = readability.problems("Jane\n", name="Jane", headings=[], keywords=[], pages=2)
    assert "empty" in kinds(found)
    assert readability.MIN_CHARS_PER_PAGE == 30


def test_normalisation_accents_case_whitespace():
    text = "Jane  DOE\nProfile\n" + "x" * 40 + "\nEXPÉRIENCE\nwork\nSkills   &  Tools\nPython\n"
    found = readability.problems(text, name=NAME, headings=["Profile", "Expérience", "Skills & Tools"], keywords=["python"])
    assert found == []


def test_missing_keyword():
    found = readability.problems(GOOD, name=NAME, headings=[], keywords=["Python", "Kubernetes"])
    assert kinds(found) == ["missing"] and "Kubernetes" in found[0]["detail"]


def test_no_headings_skips_heading_and_order_checks():
    letter = "Jane Doe\nDear hiring manager, I am writing to apply for the role.\n"
    assert readability.problems(letter, name=NAME, headings=[], keywords=[]) == []


def test_a_narrow_no_break_space_reads_as_a_space():
    text = "Jane Doe\nProfile\nCompétences\u202f: Python et SQL pour toutes les équipes\nSkills & Tools\nPython\n"
    found = readability.problems(text, name=NAME, headings=[], keywords=["Compétences : Python"])
    assert found == []


def _make_pdf(path, pages):
    return make_pdf(path, pages)


def test_extract_text_and_page_count(tmp_path):
    pdf = _make_pdf(tmp_path / "a.pdf", ["Hello first page", "Second page here"])
    text, pages = readability.extract(pdf)
    assert pages == 2 and "Hello first page" in text and "Second page here" in text


def test_extract_raises_on_missing_and_corrupt(tmp_path):
    with pytest.raises(Exception):
        readability.extract(tmp_path / "nope.pdf")
    bad = tmp_path / "bad.pdf"
    bad.write_text("not a pdf")
    with pytest.raises(Exception):
        readability.extract(bad)


def test_check_pdf_reads_back(tmp_path):
    pdf = _make_pdf(tmp_path / "cv.pdf", ["Jane Doe  a long enough line of text for the page"])
    body = "<!-- Keywords: Kubernetes -->"
    found = readability.check_pdf(pdf, body, NAME)
    assert [p["kind"] for p in found] == ["missing"] and "Kubernetes" in found[0]["detail"]


def test_check_pdf_takes_a_name_that_is_not_text_as_no_name(tmp_path):
    pdf = _make_pdf(tmp_path / "cv.pdf", ["Jane Doe  a long enough line of text for the page"])
    assert readability.check_pdf(pdf, "<p>x</p>", 42) == readability.check_pdf(pdf, "<p>x</p>", None)


def test_fixable_keeps_only_what_the_tailor_can_fix():
    found = [{"kind": "missing", "detail": "a"}, {"kind": "glued", "detail": "b"}, {"kind": "empty", "detail": "c"}]
    assert readability.FIXABLE == {"missing", "overflow", "pages"}
    assert readability.fixable(found) == [{"kind": "missing", "detail": "a"}]
    assert readability.fixable([]) == []


# ---- layout (#152) ----

BODY = "<h2>Experience</h2><p>Led the consolidation of group reporting, in 2021.</p>"
PDF_TEXT = "Experience\nLed the consolidation of group re-\nporting, in 2021.\n" + "x" * 40


def test_text_that_all_reached_the_pdf_is_no_overflow():
    assert readability.overflow_problems(PDF_TEXT, BODY) == []


def test_squashing_ignores_case_punctuation_spacing_and_hyphen_breaks():
    assert readability.squash("Re-\nPorting, 2021!") == "reporting2021"
    assert readability.overflow_problems("EXPERIENCE LED THE CONSOLIDATION OF GROUP REPORTING IN 2021 " + "x" * 40, BODY) == []


def test_words_missing_from_the_pdf_are_one_overflow_naming_the_first_five():
    body = "<p>one two three four five six seven eight</p>"
    found = readability.overflow_problems("one two three " + "x" * 40, body)
    assert kinds(found) == ["overflow"]
    detail = found[0]["detail"]
    assert detail == "text cut off: four, five, six, seven, eight"
    found = readability.overflow_problems("one " + "x" * 40, "<p>one a1 b2 c3 d4 e5 f6 g7</p>")
    assert "f6" not in found[0]["detail"] and "e5" in found[0]["detail"]


def test_the_detail_is_plain_and_has_no_instruction():
    detail = readability.overflow_problems("x" * 40, "<p>alpha</p>")[0]["detail"]
    assert detail == "text cut off: alpha" and "trim" not in detail and "page" not in detail


def test_a_word_cut_in_half_is_missing():
    assert kinds(readability.overflow_problems("Led the consolidat " + "x" * 40, "<p>Led the consolidation</p>")) == ["overflow"]


def test_a_body_with_no_words_has_no_overflow():
    assert readability.overflow_problems(PDF_TEXT, "<!-- Keywords: a -->") == []


def test_sparse_last_page_of_a_two_column_template():
    full = page((60, 60, 70, 780))
    last = page((60, 700, 70, 760))  # 60pt of ink on an 842pt page
    assert kinds(readability.layout_problems([full, last], two_column=True)) == ["sparse"]
    assert readability.layout_problems([full, last], two_column=False) == []


def test_a_blank_last_page_of_a_two_column_cv_is_sparse():
    assert kinds(readability.layout_problems([page((60, 60, 70, 780)), page()], two_column=True)) == ["sparse"]


def test_check_pdf_reads_two_column_from_the_placed_body(tmp_path, monkeypatch):
    from door.tailoring import pdf_render

    pdf = make_pdf(tmp_path / "a.pdf", [GOOD, "x"])
    monkeypatch.setattr(pdf_render, "page_boxes", lambda p: [(595.0, 842.0, [(60, 60, 70, 780)]), (595.0, 842.0, [(60, 700, 70, 710)])])
    placed = '<div class="main"><p>Jane Doe</p></div><div class="side"><p>Python</p></div>'
    assert "sparse" in kinds(readability.check_pdf(pdf, placed, NAME, cv=True))
    assert "sparse" not in kinds(readability.check_pdf(pdf, "<p>Jane Doe Python</p>", NAME, cv=True))
    assert "sparse" not in kinds(readability.check_pdf(pdf, placed, NAME))


def test_sparse_needs_more_than_one_page_and_a_nearly_empty_last():
    assert readability.layout_problems([page((60, 700, 70, 760))], two_column=True) == []
    full = page((60, 60, 70, 780))
    assert readability.layout_problems([full, page((60, 100, 70, 700))], two_column=True) == []


def test_check_pdf_of_a_letter_does_no_layout_or_overflow_check(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [GOOD])
    assert "overflow" not in kinds(readability.check_pdf(pdf, "<p>zzzunseenword</p>", NAME))


def test_check_pdf_for_a_cv_reports_words_that_never_reached_the_pdf(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [GOOD])
    found = readability.check_pdf(pdf, "<p>Jane Doe zzzunseenword</p>", NAME, cv=True)
    assert "overflow" in kinds(found) and "zzzunseenword" in [p for p in found if p["kind"] == "overflow"][0]["detail"]
    assert "overflow" not in kinds(readability.check_pdf(pdf, "<p>Jane Doe Python</p>", NAME, cv=True))


def test_no_overflow_is_said_for_a_pdf_with_no_readable_text(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [""])
    found = readability.check_pdf(pdf, "<p>some words here</p>", NAME, cv=True)
    assert "empty" in kinds(found) and "overflow" not in kinds(found)


def test_side_headings_read_in_the_wrong_order_are_reported():
    text = "Experience\nx\nSkills\ny\nProfile\n"
    found = readability.problems(text, name=None, headings=["Profile", "Experience", "Skills"], keywords=[])
    assert "order" in kinds(found)


def page(*boxes, size=(595.0, 842.0)):
    return (size[0], size[1], list(boxes))


SIDE_FIRST = (
    "Skills & Tools\nPython, SQL, Airflow, dbt\n"
    "Jane Doe\nSenior data engineer with many years of building pipelines.\n"
    "Profile\nI build data platforms in Python and SQL.\n"
    "Experience\nAcme: led a team that shipped Airflow jobs.\n"
)


def test_side_heading_reading_first_is_fine():
    found = readability.problems(SIDE_FIRST, name=NAME, headings=["Profile", "Experience"], side=["Skills & Tools"],
                                 keywords=[])
    assert found == []


def test_main_out_of_order_still_flagged_with_a_side_column():
    text = "Skills & Tools\nPython\nJane Doe\nExperience\nAcme\nProfile\nabout me\n"
    found = readability.problems(text, name=NAME, headings=["Profile", "Experience"], side=["Skills & Tools"],
                                 keywords=[])
    assert "order" in kinds(found)


def test_side_out_of_order_among_themselves_flagged():
    text = "Languages\nEnglish\nSkills\nPython\n" + GOOD
    found = readability.problems(text, name=NAME, headings=["Profile", "Experience"], side=["Skills", "Languages"],
                                 keywords=[])
    assert "order" in kinds(found)


def test_side_heading_sharing_a_line_is_not_glued():
    text = GOOD.replace("Experience\n", "Skills & Tools Experience\n").replace("Skills & Tools\n", "")
    found = readability.problems(text, name=NAME, headings=["Profile"], side=["Skills & Tools"], keywords=[])
    assert found == []


def test_missing_side_heading_still_missing():
    found = readability.problems(GOOD.replace("Skills & Tools\n", ""), name=NAME, headings=["Profile"],
                                 side=["Skills & Tools"], keywords=[])
    assert kinds(found) == ["missing"]


def test_page_split_main_column_passes():
    # page 1 reads main, then the side column; the rest of main follows on page 2
    text = "Jane Doe\nProfile\nabout me\nExperience\nAcme\nSkills & Tools\nPython\nEducation\nUniversity\n"
    found = readability.problems(text, name=NAME, headings=["Profile", "Experience", "Education"],
                                 side=["Skills & Tools"], keywords=[])
    assert found == []


def test_check_pdf_splits_main_and_side(tmp_path):
    pdf = tmp_path / "cv.pdf"
    make_pdf(pdf, [SIDE_FIRST])
    body = ('<h1>Jane Doe</h1><div class="main"><h2>Profile</h2><p>x</p><h2>Experience</h2><p>y</p></div>'
            '<div class="side"><h2>Skills &amp; Tools</h2><p>z</p></div>')
    assert readability.check_pdf(pdf, body, NAME) == []


def test_a_cv_over_its_page_limit_is_a_fixable_problem_that_names_the_limit(tmp_path):
    """#194: more pages than `cv_max_pages` is retried like a missing heading; the detail tells the tailor the limit."""
    pdf = make_pdf(tmp_path / "a.pdf", [GOOD, GOOD])
    over = [p for p in readability.check_pdf(pdf, "<p>Jane Doe</p>", NAME, cv=True, max_pages=1) if p["kind"] == "pages"]
    assert over == [{"kind": "pages", "detail": "2 pages, over the limit of 1 page"}]
    assert readability.fixable(over) == over


def test_a_cv_within_its_limit_or_a_letter_or_no_limit_has_no_pages_problem(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [GOOD, GOOD])
    assert "pages" not in kinds(readability.check_pdf(pdf, "<p>Jane Doe</p>", NAME, cv=True, max_pages=2))
    assert "pages" not in kinds(readability.check_pdf(pdf, "<p>Jane Doe</p>", NAME, max_pages=1))
    assert "pages" not in kinds(readability.check_pdf(pdf, "<p>Jane Doe</p>", NAME, cv=True))
