"""Unit tests for tailoring/readability.py: the ATS read-back of a compiled PDF. Offline."""

import pytest

from door.tailoring import readability
from pdf_utils import make_pdf

NAME = "Jane Doe"
HEADINGS = ["Profile", "Experience", "Skills \\& Tools"]
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
    found = readability.problems(text, name=NAME, headings=["Profile", "Expérience", "Skills \\& Tools"], keywords=["python"])
    assert found == []


def test_missing_keyword():
    found = readability.problems(GOOD, name=NAME, headings=[], keywords=["Python", "Kubernetes"])
    assert kinds(found) == ["missing"] and "Kubernetes" in found[0]["detail"]


def test_no_headings_skips_heading_and_order_checks():
    letter = "Jane Doe\nDear hiring manager, I am writing to apply for the role.\n"
    assert readability.problems(letter, name=NAME, headings=[], keywords=[]) == []


def test_headings_and_keywords_from_tex():
    tex = "% Keywords: Python, Airflow\n\\section{Profile}\n\\section*{Skills \\& Tools}\n"
    assert readability.headings_from_tex(tex) == ["Profile", "Skills \\& Tools"]
    assert readability.keywords_from_tex(tex) == ["Python", "Airflow"]
    assert readability.keywords_from_tex("nothing") == []


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
    tex = "% Keywords: Kubernetes\n"
    found = readability.check_pdf(pdf, tex, NAME)
    assert [p["kind"] for p in found] == ["missing"] and "Kubernetes" in found[0]["detail"]


def test_fixable_keeps_only_what_the_tailor_can_fix():
    found = [{"kind": "missing", "detail": "a"}, {"kind": "glued", "detail": "b"}, {"kind": "empty", "detail": "c"}]
    assert readability.FIXABLE == {"missing"}
    assert readability.fixable(found) == [{"kind": "missing", "detail": "a"}]
    assert readability.fixable([]) == []
