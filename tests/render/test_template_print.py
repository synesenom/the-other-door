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
from door.render import pdf_render, readability
from paths import REPO_ROOT, TESTS_DIR
from pdf_utils import font_names, image_count, page_count

pytestmark = [  # `real_chromium`: the offline suite otherwise hides the developer's Chromium (tests/conftest.py)
    pytest.mark.real_chromium,
    # CI installs the pinned shell (tests.yml), so a missing one there is a failure, not a skip
    pytest.mark.skipif(chromium.find_chromium() is None and not os.environ.get("CI"),
                       reason="no Chromium headless shell installed"),
]

FIXTURES = TESTS_DIR / "tailoring" / "fixtures"  # example CV and letter, french: shared with the facts and prepare tests
TEMPLATES = TESTS_DIR / "render" / "fixtures"
NB = " "


def _setup(tmp_path, monkeypatch, *, cv, letter, posting=None, photo=False, extra=None):
    """A job folder holding the two bodies, printed by `compile`; returns the folder and the results by file."""
    profile = tmp_path / "profile"
    profile.mkdir(parents=True)
    config = {"name": "Jane Doe", "location": "Copenhagen", **(extra or {})}
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
    assert readability.check_pdf(out / "cv.pdf", cv, "Jane Doe", cv=True) == []
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
    assert readability.check_pdf(out / "cv.pdf", cv, None, cv=True) == []


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


# --- a tagline and a kind on each contact span (#189) ---------------------------------------------------------

_KINDS = ('<header class="cv-header"><<photo>><h1>Jane Doe</h1><p class="tagline">Financial Controller | Group Reporting</p>'
          '<p class="contact"><span class="phone">+45 00 00 00 00</span>'
          '<span class="email"><a href="mailto:jane.doe@example.com">jane.doe@example.com</a></span>'
          '<span class="web"><a href="https://janedoe.example.com">janedoe.example.com</a></span>'
          '<span class="linkedin"><a href="https://www.linkedin.com/in/janedoe">linkedin.com/in/janedoe</a></span>'
          '<span class="github"><a href="https://github.com/janedoe">github.com/janedoe</a></span>'
          '<span class="location">Copenhagen</span></p></header>'
          "<h2>Profile</h2><p>Jane Doe is a financial controller with a long record in group reporting.</p>")
_PLAIN = _KINDS.replace(' class="phone"', "").replace(' class="email"', "").replace(' class="web"', "") \
    .replace(' class="linkedin"', "").replace(' class="github"', "").replace(' class="location"', "") \
    .replace('<p class="tagline">Financial Controller | Group Reporting</p>', "")
_LETTER_KINDS = ('<header class="letter-header"><h1>Jane Doe</h1><p class="contact"><span class="phone">+45 00 00 00 00</span>'
                 '<span class="location">Copenhagen</span></p></header><p>Dear team, Jane Doe writes about the role.</p>')


def test_a_tagline_and_the_kind_classed_details_print_and_read_back(tmp_path, monkeypatch):
    out, results = _setup(tmp_path, monkeypatch, cv=_KINDS, letter=_LETTER_KINDS)
    assert [r["status"] for r in results.values()] == ["compiled", "compiled"], results
    assert results["cv.html"]["readable"] == [] and results["cover_letter.html"]["readable"] == []
    lines = _lines(out / "cv.pdf")
    assert "Financial Controller | Group Reporting" in lines, lines
    # the six details are too long for one line at 9pt: it breaks between two of them, the dot ending the first line
    start = next(i for i, line in enumerate(lines) if line.startswith("+45 00 00 00 00 · jane.doe@example.com"))
    details = " ".join(lines[start:start + 2])
    assert "linkedin.com/in/janedoe · github.com/janedoe · Copenhagen" in details, lines
    assert lines[start].endswith("·") and not lines[start + 1].startswith("·"), lines
    assert lines.index("Financial Controller | Group Reporting") == lines.index("Jane Doe") + 1


def test_kind_classes_do_not_change_the_details_text(tmp_path, monkeypatch):
    kinds, _ = _setup(tmp_path / "a", monkeypatch, cv=_KINDS.replace('<p class="tagline">Financial Controller | Group Reporting</p>', ""),
                      letter=_LETTER)
    plain, _ = _setup(tmp_path / "b", monkeypatch, cv=_PLAIN, letter=_LETTER)
    assert pdf_render.page_texts(kinds / "cv.pdf") == pdf_render.page_texts(plain / "cv.pdf")


def test_a_photo_header_with_a_tagline_puts_it_under_the_name_beside_the_picture(tmp_path, monkeypatch):
    out, results = _setup(tmp_path, monkeypatch, cv=_KINDS, letter=_LETTER, photo=True)
    assert results["cv.html"]["photo"] == "photo.jpg" and results["cv.html"]["readable"] == []
    lines = _lines(out / "cv.pdf")
    assert lines.index("Financial Controller | Group Reporting") == lines.index("Jane Doe") + 1
    assert image_count(out / "cv.pdf") == 1 and page_count(out / "cv.pdf") == 1


# --- icons drawn by a template (#189) ---------------------------------------------------------------------------

def _colours(pdf_path):
    """The (red, green) pixel counts of the first page, drawn by pdfium."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        image = pdf[0].render(scale=1).to_pil().convert("RGB")
    finally:
        pdf.close()
    pixels = list(image.getdata())
    return (sum(1 for r, g, b in pixels if r > 200 and g < 60 and b < 60),
            sum(1 for r, g, b in pixels if g > 200 and r < 60 and b < 60))


def test_a_template_with_icons_draws_them_beside_the_details_it_names(tmp_path, monkeypatch):
    template = TEMPLATES / "icon_template" / "cv.template.html"
    out, results = _setup(tmp_path, monkeypatch, cv=_KINDS, letter=_LETTER, extra={"cv_template": str(template)})
    assert results["cv.html"]["status"] == "compiled", results["cv.html"]
    red, green = _colours(out / "cv.pdf")
    assert red > 50 and green > 50, (red, green)
    assert results["cv.html"]["readable"] == []


def test_the_same_template_without_its_manifest_draws_no_icon(tmp_path, monkeypatch):
    import shutil

    copy = tmp_path / "tpl"
    copy.mkdir()
    shutil.copy(TEMPLATES / "icon_template" / "cv.template.html", copy)  # no template.json, no icons/
    out, results = _setup(tmp_path / "job", monkeypatch, cv=_KINDS, letter=_LETTER,
                          extra={"cv_template": str(copy / "cv.template.html")})
    assert results["cv.html"]["status"] == "compiled", results["cv.html"]
    assert _colours(out / "cv.pdf") == (0, 0)


def test_the_default_template_draws_no_icon(tmp_path, monkeypatch):
    out, _ = _setup(tmp_path, monkeypatch, cv=_KINDS, letter=_LETTER)
    assert _colours(out / "cv.pdf")[0] == 0


# --- entries and levels (#147) ----------------------------------------------------------------------------------

_SPAN_ENTRY = ('<h3><span class="role">Financial Controller</span><span class="sep"> | </span><span class="org">Globex Energy</span>'
               '<span class="sep"> - </span><span class="dates">2021 - present</span><span class="sep"> | </span>'
               '<span class="place">Aarhus</span></h3>')
_PLAIN_ENTRY = "<h3>Financial Controller | Globex Energy - 2021 - present | Aarhus</h3>"
_LEVELS = ('<h2>Languages</h2><ul><li><strong>Danish</strong> <span class="level level-5">native</span></li><li><strong>English</strong> <span class="level level-4">fluent</span></li>'
           '<li><strong>French</strong> <span class="level level-1">basic</span></li></ul>')


def _entries(entry):
    return (f'{_HEADER}<h2>Experience</h2><div class="entry">{entry}<ul><li>Closed the books in four days.</li></ul></div>'
            f"{_LEVELS}")


def test_span_entry_headings_and_level_items_print_and_read_back(tmp_path, monkeypatch):
    out, results = _setup(tmp_path, monkeypatch, cv=_entries(_SPAN_ENTRY), letter=_LETTER)
    assert results["cv.html"]["status"] == "compiled", results["cv.html"]
    assert results["cv.html"]["readable"] == []
    lines = _lines(out / "cv.pdf")
    assert "Financial Controller | Globex Energy - 2021 - present | Aarhus" in lines, lines
    for word in ("Danish native", "English fluent", "French basic"):
        assert word in lines, lines


def test_a_plain_entry_heading_prints_the_same_text_as_the_span_one(tmp_path, monkeypatch):
    spans, _ = _setup(tmp_path / "a", monkeypatch, cv=_entries(_SPAN_ENTRY), letter=_LETTER)
    plain, _ = _setup(tmp_path / "b", monkeypatch, cv=_entries(_PLAIN_ENTRY), letter=_LETTER)
    assert pdf_render.page_texts(spans / "cv.pdf") == pdf_render.page_texts(plain / "cv.pdf")


# --- two columns (#147) -----------------------------------------------------------------------------------------

_TWO_COLUMNS = (_HEADER + '<h2>Experience</h2><div class="entry"><h3>Controller | Globex Energy - 2021</h3>'
                '<ul><li>Closed the books in four days.</li></ul></div>'
                '<h2>Skills</h2><p>IFRS, SQL</p><h2>Education</h2><p>MSc, CBS</p>'
                '<h2>Languages</h2><ul><li><strong>Danish</strong> <span class="level level-5">native</span></li></ul>')


def test_a_two_column_template_prints_every_heading_on_a_line_and_the_side_after_the_main(tmp_path, monkeypatch):
    template = TEMPLATES / "columns_template" / "cv.template.html"
    out, results = _setup(tmp_path, monkeypatch, cv=_TWO_COLUMNS, letter=_LETTER, extra={"cv_template": str(template)})
    assert results["cv.html"]["status"] == "compiled", results["cv.html"]
    assert results["cv.html"]["readable"] == []
    lines = _lines(out / "cv.pdf")
    for heading in ("Experience", "Skills", "Education", "Languages"):
        assert heading in lines, lines
    assert lines.index("Education") < lines.index("Skills") < lines.index("Languages"), lines
    assert "Danish native" in lines and page_count(out / "cv.pdf") == 1


def test_the_default_template_keeps_one_column_in_the_bodys_order(tmp_path, monkeypatch):
    out, results = _setup(tmp_path, monkeypatch, cv=_TWO_COLUMNS, letter=_LETTER)
    assert results["cv.html"]["readable"] == []
    lines = _lines(out / "cv.pdf")
    assert lines.index("Skills") < lines.index("Education") < lines.index("Languages"), lines


def test_a_two_column_template_with_a_line_that_cannot_wrap_reports_the_cut_words_as_overflow(tmp_path, monkeypatch):
    template = TEMPLATES / "overflow_template" / "cv.template.html"  # the side column's lines never wrap
    cv = _TWO_COLUMNS.replace("<p>IFRS, SQL</p>", "<ul><li>" + "Consolidation and reporting under IFRS, " * 6 + "</li></ul>")
    out, results = _setup(tmp_path, monkeypatch, cv=cv, letter=_LETTER, extra={"cv_template": str(template)})
    assert results["cv.html"]["status"] == "compiled", results["cv.html"]
    found = results["cv.html"]["readable"]
    assert [p["kind"] for p in found] == ["overflow"], found
    assert "IFRS" in found[0]["detail"] or "reporting" in found[0]["detail"], found


@pytest.mark.parametrize("width", [180, 198, 288])  # widths at which the heading broke before " | " or " - "
def test_an_entry_heading_never_starts_a_line_with_its_separator(tmp_path, width):
    """#246: a heading too long for its line breaks after the separator, never before it."""
    template = ("<!doctype html><html lang=\"<<lang>>\"><head><style>@page { size: %dpt 300pt; margin: 10pt; } " % width +
                "body { font: 12pt sans-serif; } .photo { width: 1pt; }</style></head><body>\n<<body>>\n</body></html>")
    body = ('<div class="entry"><h3><span class="role">Junior Financial Analyst</span><span class="sep"> | </span>'
            '<span class="org">Example Co</span><span class="sep"> - </span><span class="dates">2020 - 2023</span></h3></div>')
    pdf = compile_cmd.print_page(body, template, REPO_ROOT / "profile.example" / "cv.template.html", "en", tmp_path, "cv")[0]
    lines = [line.strip() for line in pdf_render.page_texts(pdf)[0].splitlines() if line.strip()]
    assert len(lines) > 1 and not [line for line in lines if line[0] in "|-"], lines
