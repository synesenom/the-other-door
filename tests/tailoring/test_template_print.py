"""The shipped templates, really printed by the pinned Chromium (#146, #357, #623, #142, #143, #389).

Part of the offline suite (marker `real_chromium`). Skipped where no Chromium headless shell is installed
(`./door doctor --fix`, or `DOOR_BIN`), but not in CI, which installs it. These pin each template
feature: the photo header and the one-line header without it, French typography and date, the page limit, TrueType
fonts (no nameless Type 3 text), no automatic hyphenation, and that an ATS reads the pages back cleanly."""

import io
import json
import os
import re
from datetime import date

import pytest
from PIL import Image

from door import i18n
from door.commands import compile as compile_cmd
from door.core import chromium, workspace
from door.tailoring import pdf_render, readability
from paths import REPO_ROOT, TESTS_DIR
from pdf_utils import font_names, image_count, page_count

pytestmark = [  # `real_chromium`: the offline suite otherwise hides the developer's Chromium (tests/conftest.py)
    pytest.mark.real_chromium,
    # CI installs the pinned shell (tests.yml), so a missing one there is a failure, not a skip
    pytest.mark.skipif(chromium.find_chromium() is None and not os.environ.get("CI"),
                       reason="no Chromium headless shell installed"),
]

FIXTURES = TESTS_DIR / "tailoring" / "fixtures"
NB = " "


def _setup(tmp_path, monkeypatch, *, cv, letter, posting=None, photo=False):
    """A job folder holding the two bodies, printed by `compile`; returns the folder and the results by file."""
    profile = tmp_path / "profile"
    profile.mkdir()
    config = {"name": "Jane Doe", "location": "Copenhagen"}
    if photo:
        buf = io.BytesIO()
        Image.new("RGB", (350, 450), "tan").save(buf, "JPEG")
        (profile / "photo.jpg").write_bytes(buf.getvalue())
        config["photo"] = str(profile / "photo.jpg")
    (profile / "config.json").write_text(json.dumps(config))
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    out = tmp_path / "jobs" / "output" / "job"
    out.mkdir(parents=True)
    (out / "posting.json").write_text(json.dumps(posting or {"title": "Head of Finance", "company": "Globex Energy",
                                                            "location": "Aarhus"}))
    (out / "cv.html").write_text(cv, encoding="utf-8")
    (out / "cover_letter.html").write_text(letter, encoding="utf-8")
    result = compile_cmd._compile_core("job", jobs_dir=tmp_path / "jobs")
    return out, {r["file"]: r for r in result["results"]}


def _gap(path, word, mark):
    """The space, in points, between the last letter of `word` and the `mark` that follows it on the page (the PDF's
    text holds no character for the space itself: Chromium writes it as a move)."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        textpage = pdf[0].get_textpage()
        text = textpage.get_text_range()
        found = re.search(re.escape(word) + r"\s?" + re.escape(mark), text)  # pdfium may or may not read a space
        last, at_mark = found.start() + len(word) - 1, found.end() - 1
        return textpage.get_charbox(at_mark)[0] - textpage.get_charbox(last)[2]
    finally:
        pdf.close()


def _lines(path, index=0):
    text = pdf_render.page_texts(path)[index].replace(" ", " ").replace(" ", " ")
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


@pytest.fixture(scope="module")
def example(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        tmp = tmp_path_factory.mktemp("example")
        cv = (FIXTURES / "example_cv.html").read_text(encoding="utf-8")
        letter = (FIXTURES / "example_cover_letter.html").read_text(encoding="utf-8")
        out, results = _setup(tmp, mp, cv=cv, letter=letter)
    return out, results, cv


@pytest.mark.parametrize("name", ["cv", "cover_letter"])
def test_the_example_prints_within_its_page_limit(example, name):
    out, results, _ = example
    assert results[f"{name}.html"]["status"] == "compiled", results[f"{name}.html"].get("stderr")
    limit = 2 if name == "cv" else 1
    assert 1 <= page_count(out / f"{name}.pdf") <= limit


@pytest.mark.parametrize("name", ["cv", "cover_letter"])
def test_the_fonts_are_the_templates_own_truetype_ones_never_nameless_type_3_text(example, name):
    out, _, _ = example
    names = font_names(out / f"{name}.pdf")
    assert names and all(n for n in names), names  # a CFF font is written as Type 3 text with no name
    assert any(n.startswith("Figtree") for n in names) and any(n.startswith("YoungSerif") for n in names), names


def test_the_example_cv_reads_back_with_every_heading_on_its_own_line_and_in_order(example):
    out, results, cv = example
    assert readability.check_pdf(out / "cv.pdf", cv, "Jane Doe") == []
    assert results["cv.html"]["readable"] == []
    assert results["cover_letter.html"]["readable"] == []


def test_the_letter_prints_its_date_and_sign_off(example):
    out, _, _ = example
    lines = _lines(out / "cover_letter.pdf")
    assert i18n.format_date(date.today(), "en") in lines and "Kind regards," in lines


# --- the header (#142, #605) -------------------------------------------------------------------------------

_HEADER = ('<header class="cv-header"><<photo>><h1>Jane Doe</h1><p class="contact"><span>+45 00 00 00 00</span>'
           '<span><a href="mailto:jane.doe@example.com">jane.doe@example.com</a></span>'
           '<span><a href="https://janedoe.example.com">janedoe.example.com</a></span><span>Copenhagen</span></p></header>'
           "<h2>Profile</h2><p>Jane Doe is a financial controller with a long record in group reporting.</p>")
_LETTER = '<header class="letter-header"><h1>Jane Doe</h1></header><p>Dear team, Jane Doe writes about the role.</p>'


def test_without_a_photo_the_details_sit_on_one_line_apart_by_dots(tmp_path, monkeypatch):
    out, results = _setup(tmp_path, monkeypatch, cv=_HEADER, letter=_LETTER)
    assert "photo" not in results["cv.html"]
    lines = _lines(out / "cv.pdf")
    assert "+45 00 00 00 00 · jane.doe@example.com · janedoe.example.com · Copenhagen" in lines, lines
    assert image_count(out / "cv.pdf") == 0


def test_with_a_photo_the_picture_is_beside_the_name_and_the_details_stack(tmp_path, monkeypatch):
    out, results = _setup(tmp_path, monkeypatch, cv=_HEADER, letter=_LETTER, photo=True)
    assert results["cv.html"]["photo"] == "photo.jpg" and results["cv.html"]["readable"] == []
    assert image_count(out / "cv.pdf") == 1
    lines = _lines(out / "cv.pdf")
    for detail in ("+45 00 00 00 00", "jane.doe@example.com", "janedoe.example.com", "Copenhagen"):
        assert detail in lines, lines
    assert page_count(out / "cv.pdf") == 1


def test_the_photo_sits_at_the_right_of_the_name_not_under_it(tmp_path, monkeypatch):
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    out, _ = _setup(tmp_path, monkeypatch, cv=_HEADER, letter=_LETTER, photo=True)
    pdf = pdfium.PdfDocument(str(out / "cv.pdf"))
    try:
        page = pdf[0]
        image = next(page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE]))
        left, bottom, right, top = image.get_bounds()
        text = page.get_textpage()
        name_right = max(text.get_charbox(i)[2] for i in range(len("Jane Doe")))
        assert left > name_right, (left, name_right)
        assert top > page.get_height() / 2 and (right - left) == pytest.approx(2.2 / 2.54 * 72, rel=0.05)
    finally:
        pdf.close()


# --- French (#143, #389) ------------------------------------------------------------------------------------

def test_a_french_cv_and_letter_get_french_typography_date_and_links_untouched(tmp_path, monkeypatch):
    cv = (FIXTURES / "french" / "cv_body.html").read_text(encoding="utf-8").replace(
        "</p>\n\n<h2>Expérience", '</p>\n<p><a href="https://arxiv.org/abs/2408.10754?a=b">arXiv:2408.10754</a></p>\n\n<h2>Expérience', 1)
    letter = (FIXTURES / "french" / "letter_body.html").read_text(encoding="utf-8")
    out, results = _setup(tmp_path, monkeypatch, cv=cv, letter=letter, posting={
        "title": "Responsable des ventes", "company": "Soleil Énergie", "location": "Lyon", "language": "fr"})
    assert [r["status"] for r in results.values()] == ["compiled", "compiled"], results
    letter_text = " ".join(pdf_render.page_texts(out / "cover_letter.pdf")[0].replace("\u202f", " ").split())
    assert f"Lyon, le {i18n.format_date(date.today(), 'fr')}" in letter_text
    assert "\u00ab" in letter_text and "Ensemble, allons plus loin" in letter_text
    # the narrow no-break space is a gap in the page: before a colon, inside the guillemets
    assert _gap(out / "cover_letter.pdf", "Objet", ":") > 1.8
    assert _gap(out / "cover_letter.pdf", "loin", "\u00bb") > 1.8
    assert _gap(out / "cv.pdf", "donn\u00e9es", ":") > 1.8 and _gap(out / "cv.pdf", "r\u00e9sultats", "!") > 1.8
    cv_text = pdf_render.page_texts(out / "cv.pdf")[0]
    assert "arXiv:2408.10754" in cv_text and _gap(out / "cv.pdf", "arXiv", ":") < 1.5
    assert readability.check_pdf(out / "cv.pdf", cv, None) == []


def test_the_same_text_in_english_keeps_its_plain_spaces(tmp_path, monkeypatch):
    cv = "<h2>Profile</h2><p>Skills: Python; SQL! Really? Yes.</p>"
    out, _ = _setup(tmp_path, monkeypatch, cv=cv, letter=_LETTER)
    assert _gap(out / "cv.pdf", "Skills", ":") < 1.5 and _gap(out / "cv.pdf", "Python", ";") < 1.5


# --- no automatic hyphenation (#146) ---------------------------------------------------------------------------

def test_no_word_is_split_at_a_line_end_without_a_soft_hyphen(tmp_path, monkeypatch):
    words = " ".join(["Donaudampfschifffahrtsgesellschaftskapitaensmuetze", "internationalisation", "responsibilities"] * 14)
    out, _ = _setup(tmp_path, monkeypatch, cv=f"<h2>Profile</h2><p>{words}</p>", letter=_LETTER)
    text = pdf_render.page_texts(out / "cv.pdf")[0]
    assert len(text.splitlines()) > 5  # it wrapped
    assert not re.search(r"\w-\n", text), text  # no hyphen was added where a line broke
