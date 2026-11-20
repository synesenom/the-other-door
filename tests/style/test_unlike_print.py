"""A CV set in a font no free family looks like, really printed by the pinned Chromium: its look is not offered
(`fonts.unlike`, `style._look`), while the same CV set in a pinned family is. The counter-case to the corpus, where
every CV has a look-alike. Marked `real_chromium` like test_template_print.py."""

import os

import pytest
from fontTools.ttLib import TTFont

from door.commands import style as style_cmd
from door.core import workspace
from door.core.downloads import chromium
from door.render import html_pdf
from door.style import font_measure, fonts, style_extract, style_structure

pytestmark = [
    pytest.mark.real_chromium,
    pytest.mark.skipif(chromium.find_chromium() is None and not os.environ.get("CI"),
                       reason="no Chromium headless shell installed"),
]

BODY = ("<h1>Jane Doe</h1><h2>Profile</h2><p>Engineer with ten years in energy markets, leading a team of five "
        "analysts and building the forecasting models the trading desk runs every morning.</p>"
        "<h2>Experience</h2><p>Lead analyst at Globex, 2019 to today. Analyst at Initech, 2015 to 2019.</p>") * 3


def _cv(tmp_path, family: str):
    """The CV printed in Figtree renamed `family`: the same shapes and widths under a name of its own."""
    font = TTFont(workspace.PROFILE_EXAMPLE_DIR / "fonts" / "Figtree-Regular.ttf")
    for rec in font["name"].names:
        if rec.nameID in (1, 4, 16):
            rec.string = family
        elif rec.nameID == 6:
            rec.string = family.replace(" ", "") + "-Regular"
    font.save(tmp_path / "face.ttf")
    html = (f"<!doctype html><meta charset=utf-8><style>@font-face{{font-family:F;src:url(face.ttf)}}"
            f"body{{font-family:F;font-size:10pt}}</style><body>{BODY}</body>")
    html_pdf.print_html(tmp_path, html, tmp_path / "cv.pdf")
    return tmp_path / "cv.pdf"


def _unlike(pdf):
    used = style_extract.fonts_used(style_extract.read_pages(pdf))
    return fonts.unlike(fonts.plan(used, font_measure.measure(pdf, used)), used)


def test_a_cv_in_an_unknown_font_with_only_a_width_match_has_no_look_to_copy(tmp_path, monkeypatch):
    pdf = _cv(tmp_path, "Zorblax Grotesk")
    assert _unlike(pdf) == ["Zorblax Grotesk"]
    # refused before the one model call: nothing is spent on a CV whose look cannot be copied
    monkeypatch.setattr(style_structure, "structure_for", lambda *a, **k: pytest.fail("the model was asked"))
    with pytest.raises(ValueError, match="is set in Zorblax Grotesk, which has no free font that looks like it"):
        style_cmd._look(pdf)


def test_the_same_cv_in_a_pinned_family_has_its_look(tmp_path):
    assert _unlike(_cv(tmp_path, "Figtree")) == []
