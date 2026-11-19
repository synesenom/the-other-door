"""What `fonts.plan` makes of the fonts of the style corpus (#148), measured off the PDFs (#199), against the real pin."""

import pytest

from paths import TESTS_DIR

from door.style import fonts
from door.style import font_measure, style_extract

STYLES = TESTS_DIR / "style" / "fixtures" / "styles"

# (pdf, CV family) -> (source, resolved family, or the class a nearest one must be of)
CASES = [
    ("html-plain-single", "Young Serif", "name", "Young Serif"),
    ("scrubbed-altacv-icons-fr", "Lato", "name", "Lato"),
    ("latex-altacv", "TeXGyreHeros", "standin", "Arimo"),
    ("latex-sidebar", "Nimbus Sans L", "standin", "Arimo"),
    ("html-plain-single", "Figtree", "nearest", "sans"),        # variable on google/fonts: never pinned
    ("scrubbed-pages-sidebar-fr", "Optima", "lookalike", "Asap"),  # Apple's, not free
    ("scrubbed-pages-header-en", "AvenirNext", "lookalike", "Lato"),  # Apple's, not free
    ("latex-classic", "URW Palladio L", "nearest", "serif"),
    ("latex-two-column", "LMRoman10", "nearest", "serif"),
    ("latex-two-column", "LMRoman12", "none", "Tinos"),         # one short run: nothing to measure
]


@pytest.fixture(scope="module")
def plans():
    out = {}
    for stem in {c[0] for c in CASES} | {"scrubbed-altacv-icons-fr", "latex-classic"}:
        pdf = STYLES / f"{stem}.pdf"
        found = style_extract.extract(pdf)["fonts"]
        out[stem] = {p["family"]: p for p in fonts.plan(found, font_measure.measure(pdf, found))}
    return out


@pytest.mark.parametrize("stem,family,source,expected", CASES)
def test_the_plan_for_a_corpus_font(plans, stem, family, source, expected):
    entry = plans[stem][family]
    assert entry["source"] == source
    if source == "nearest":
        assert fonts.pin()["families"][entry["resolved"]]["class"] == expected
        assert entry["files"] and entry["licence"] and 1 <= len(entry["alternatives"]) <= 2
    else:
        assert entry["resolved"] == expected
    assert entry["reason"].startswith(family)


def test_an_icon_font_is_left_out_of_the_plan(plans):
    assert "FontAwesome" not in plans["scrubbed-altacv-icons-fr"]
    assert "Computer Modern" not in plans["latex-classic"]   # CMSY10, drawn as an icon here


def test_a_symbol_font_that_is_no_icon_gets_none():
    [entry] = fonts.plan([{"font": "CMSY10", "family": "Computer Modern", "weight": 400, "italic": True, "serif": True,
                           "fixed": False, "embedded": True, "icon": False, "type3": False, "runs": 1, "chars": 2}])
    assert (entry["source"], entry["resolved"], entry["files"]) == ("none", None, [])
