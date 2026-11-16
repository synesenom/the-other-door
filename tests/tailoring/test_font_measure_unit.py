"""Measuring the fonts of a PDF (#199) on the style corpus: Lato's x-height is 0.507 em."""

import pytest

from paths import TESTS_DIR

from door.tailoring import font_measure, style_extract

STYLES = TESTS_DIR / "tailoring" / "fixtures" / "styles"


@pytest.fixture(scope="module")
def lato():
    pdf = STYLES / "scrubbed-altacv-icons-fr.pdf"
    return font_measure.measure(pdf, style_extract.extract(pdf)["fonts"])


def test_the_x_height_and_stem_of_the_regular_face_are_read_off_the_glyph_boxes(lato):
    regular = lato["Lato-Regular"]
    assert regular["x_height"] == pytest.approx(0.51, abs=0.03)
    assert "cap_height" not in regular
    assert 0.03 < regular["stem"] < 0.2


def test_runs_come_with_their_width_and_size(lato):
    text, width, size = max(lato["Lato-Regular"]["runs"], key=lambda r: len(r[0]))
    assert len(text) >= 8 and 0 < width < 600 and 5 < size < 30


def test_an_icon_font_is_not_measured(lato):
    assert "FontAwesome" not in lato

