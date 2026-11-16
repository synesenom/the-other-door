"""The style corpus (#148): made-up and scrubbed CV PDFs of different designs, each read back as expected.json says
(its fonts, accent colour, column count, icon count, whether it has a photo, what to copy at all). The real CVs are
there only scrubbed (scripts/cv_style_proto/scrub_pdf.py); the made-up ones are built by scripts/make_style_corpus.py."""

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


def test_the_corpus_has_the_designs_the_epic_asks_for():
    names = " ".join(STEMS)
    for design in ("altacv", "two-column", "canva", "plain", "scan", "linkedin", "pages", "sidebar"):
        assert design in names


@pytest.mark.parametrize("stem", STEMS)
def test_the_verdict_is_what_to_copy(styles, stem):
    verdict = styles[stem]["verdict"]
    assert {k: verdict[k] for k in ("copyable", "reason")} == EXPECTED[stem]["verdict"]
    if not verdict["copyable"]:
        assert set(styles[stem]) == {"version", "verdict", "producer", "creator", "page_count"}


def _copyable():
    return [s for s in STEMS if EXPECTED[s]["verdict"]["copyable"]]


@pytest.mark.parametrize("stem", _copyable())
def test_the_fonts_are_found_by_family(styles, stem):
    families = {f["family"].casefold() for f in styles[stem]["fonts"]}
    for family in EXPECTED[stem]["fonts"]:
        assert family.casefold() in families


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


@pytest.mark.parametrize("stem", STEMS)
def test_a_fixture_stays_small(stem):
    limit = 200_000 if stem.startswith("scrubbed-") else 150_000
    assert (STYLES / f"{stem}.pdf").stat().st_size <= limit


def test_the_made_up_pdfs_name_only_example_addresses(styles):
    for stem in _copyable():
        if stem.startswith("scrubbed-"):
            continue
        for run in styles[stem]["runs"]:
            for domain in re.findall(r"@([\w.-]+\.\w+)", run["text"]):
                assert domain == "example.com", f"{stem}: {run['text']}"
