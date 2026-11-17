"""The style corpus (#148): made-up and scrubbed CV PDFs of different designs, each read back as expected.json says
(its fonts, accent colour, column count, icon count, whether it has a photo, what to copy at all). The real CVs are
there only scrubbed (scripts/style_corpus/scrub_pdf.py); the made-up ones are built by scripts/make_style_corpus.py."""

import json
import re

import pytest

from paths import TESTS_DIR

from door.tailoring import style_extract

STYLES = TESTS_DIR / "tailoring" / "fixtures" / "styles"
EXPECTED = json.loads((STYLES / "expected.json").read_text(encoding="utf-8"))
STEMS = sorted(EXPECTED)


@pytest.fixture(scope="module")
def styles():
    return {stem: style_extract.extract(STYLES / f"{stem}.pdf") for stem in STEMS}


def test_every_pdf_of_the_corpus_has_its_expectations_and_the_other_way_round():
    assert sorted(p.stem for p in STYLES.glob("*.pdf")) == STEMS


@pytest.mark.parametrize("stem", STEMS)
def test_the_verdict_is_what_to_copy(styles, stem):
    verdict = styles[stem]["verdict"]
    assert {k: verdict[k] for k in ("copyable", "reason")} == EXPECTED[stem]["verdict"]


def _copyable():
    return [s for s in STEMS if EXPECTED[s]["verdict"]["copyable"]]


@pytest.mark.parametrize("stem", _copyable())
def test_the_fonts_are_found_by_family_and_serif_or_sans(styles, stem):
    found = {f["family"].casefold(): f for f in styles[stem]["fonts"]}
    for family, serif in EXPECTED[stem]["fonts"].items():
        assert found[family.casefold()]["serif"] is serif


@pytest.mark.parametrize("stem", [s for s in _copyable() if "name_family" in EXPECTED[s]])
def test_the_name_has_the_family_of_its_font_even_when_the_pdf_leaves_it_unnamed(styles, stem):
    assert styles[stem]["name"]["family"] == EXPECTED[stem]["name_family"]


@pytest.mark.parametrize("stem", _copyable())
def test_the_accent_colour_is_found_within_a_few_steps_a_channel(styles, stem):
    found, expected = styles[stem]["colors"]["accent"], EXPECTED[stem]["accent"]
    if expected is None:
        assert found is None
    else:
        assert found is not None
        assert all(abs(int(found[i:i + 2], 16) - int(expected[i:i + 2], 16)) <= 8 for i in (1, 3, 5))


@pytest.mark.parametrize("stem", _copyable())
def test_the_columns_icons_photo_and_heading_case(styles, stem):
    style, expected = styles[stem], EXPECTED[stem]
    assert style["columns"]["count"] == expected["columns"]
    icons = expected["icons"]
    low, high = icons if isinstance(icons, list) else (icons, icons)
    assert low <= len(style["icons"]) <= high
    assert (style["photo"] is not None) == expected["photo"]
    assert style["heading_style"]["case"] == expected["heading_case"]


@pytest.mark.parametrize("stem", _copyable())
def test_a_page_has_margins_and_the_text_of_the_cv_is_read(styles, stem):
    style = styles[stem]
    assert all(m >= 0 for m in style["page"]["margins"].values())
    assert len(style["runs"]) > 20 and style["name"]["size"] > 0


def test_the_made_up_pdfs_name_only_example_addresses(styles):
    for stem in _copyable():
        if stem.startswith("scrubbed-"):
            continue
        for run in styles[stem]["runs"]:
            for domain in re.findall(r"@([\w.-]+\.\w+)", run["text"]):
                assert domain == "example.com", f"{stem}: {run['text']}"


@pytest.mark.parametrize("stem", _copyable())
def test_a_running_header_is_found_only_where_later_pages_repeat_one(styles, stem):
    """#249: scrubbed-pages-header-en repeats a line (the name and a site) at the top of page 2; no other CV does."""
    found = styles[stem]["running_header"]
    if stem == "scrubbed-pages-header-en":
        assert found["text"] == "Vent Rivage parfumerie.ours" and found["size"] == 9.0
    else:
        assert found is None
