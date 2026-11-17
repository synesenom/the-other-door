"""scripts/make_style_corpus.py: the made-up CV PDFs of the style corpus, built from HTML (#148)."""

import importlib.util
import re

import pypdfium2 as pdfium
import pypdfium2.raw as raw
from PIL import Image

from paths import REPO_ROOT
from pdf_utils import make_pdf

_spec = importlib.util.spec_from_file_location("make_style_corpus", REPO_ROOT / "scripts" / "make_style_corpus.py")
corpus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(corpus)

FONTS = {p.name for p in (REPO_ROOT / "profile.example" / "fonts").glob("*.ttf")}


def test_the_designs_are_set_in_the_fonts_of_the_example_profile_only():
    html = corpus.with_fonts(corpus.source(1))
    urls = re.findall(r"url\(/fonts/([^)]+)\)", html)
    assert urls and set(urls) <= FONTS
    assert "Figtree" in html and "Young Serif" in html


def test_the_linkedin_like_page_has_the_headings_and_page_footers_of_an_export():
    html = corpus.linkedin_html(corpus.record(4))
    for heading in ("Contact", "Top Skills", "Languages", "Certifications", "Summary", "Experience", "Education"):
        assert f">{heading}<" in html
    assert re.findall(r"Page \d of 2", html) == ["Page 1 of 2", "Page 2 of 2"]
    assert set(re.findall(r"@([\w.-]+\.\w+)", html)) == {"example.com"}


def test_a_scan_is_one_picture_and_no_text(tmp_path):
    out = tmp_path / "scan.pdf"
    corpus.scan_pdf(Image.new("RGB", (200, 300), "white"), out)
    page = pdfium.PdfDocument(str(out))[0]
    kinds = [o.type for o in page.get_objects()]
    assert kinds == [raw.FPDF_PAGEOBJ_IMAGE] and not page.get_textpage().get_text_range().strip()


def test_building_the_corpus_prints_each_html_design_and_makes_the_scan(tmp_path):
    printed = []

    def printer(folder, html, out_pdf, *, assets=None, **_):
        printed.append((out_pdf.name, sorted(p.name for p in assets["fonts"])))
        make_pdf(out_pdf, ["Printed " * 12])

    corpus.build(tmp_path, printer=printer)
    assert [n for n, _ in printed] == ["html-word-two-column.pdf", "html-canva-icons.pdf", "html-plain-single.pdf", "linkedin-like.pdf",
                                           "html-equal-columns.pdf"]
    assert all(set(fonts) <= FONTS for _, fonts in printed)
    assert (tmp_path / "scan.pdf").exists()


def test_the_made_up_cvs_use_example_addresses_only():
    for n in (1, 2, 3, 4, 5):
        c = corpus.record(n)["contact"]
        assert c["email"].endswith("@example.com") and c["web"].startswith("example.com/")


def test_the_equal_columns_design_has_two_flex_one_columns_with_the_side_kinds_on_the_left():
    html = corpus.html_equal_columns(corpus.record(5))
    assert re.findall(r"\.(left|right)\{flex:1\}", html) == ["left", "right"]
    left, right = re.search(r"class='left'>(.*)</div><div class='right'>(.*)</div></div>", html, re.S).groups()
    heads = lambda part: re.findall(r"<h2>([^<]+)</h2>", part)
    assert heads(left) == ["Contact", "Skills", "Education", "Languages"] and heads(right) == ["Profile", "Experience"]
    assert set(re.findall(r"@([\w.-]+\.\w+)", html)) == {"example.com"}
