"""The CV style builder end to end with the real Chromium (#149): a canned stylist (the model seam) on corpus PDFs, the
real print, the real stress renders, fonts from a stand-in download. Marked `real_chromium` like test_template_print.py.
Each build prints a dozen pages, so only the paths that need the browser are here: a build that passes, one that fails
the stress renders, and a published template used by `compile`. The loop's other cases, with the print stood in,
are in test_style_build_loop.py."""

import json
import os

import pytest

from door.commands import compile as compile_cmd
from door.core import chromium, templates, workspace
from door.tailoring import cv_body, html_guard, style_build, style_extract, style_preview
from pdf_utils import font_names, path_count
from style_build_utils import BIG, EXAMPLE, STYLES, Stylist, cv_only, cv_round, fake_fonts, letter_round

pytestmark = [
    pytest.mark.real_chromium,
    pytest.mark.skipif(chromium.find_chromium() is None and not os.environ.get("CI"),
                       reason="no Chromium headless shell installed"),
]

ICON_RULE = '.contact .email::before { content: ""; display: inline-block; width: 9px; height: 9px; background: url(/icons/email.svg); }'


def _build(tmp_path, pdf, stylist):
    profile = tmp_path / "profile"
    profile.mkdir(exist_ok=True)
    result = style_build.build(STYLES / f"{pdf}.pdf", profile_dir=profile, work_dir=tmp_path / "work", run=stylist,
                               fonts_fetch=fake_fonts)
    return result, profile


def test_a_good_template_builds_and_is_written_whole(tmp_path):
    stylist = Stylist(cv_round(), cv_only(), letter_round())
    result, profile = _build(tmp_path, "html-word-two-column", stylist)
    assert result["state"] == "ready", result["problems"]
    assert result["problems"] == [] and result["rounds"] >= 1 and all(0 <= s <= 1 for s in result["scores"])
    assert result["rounds"] == len(stylist.calls) - 1  # the letter's call is not a round of the CV template
    assert {f["family"] for f in result["fonts"]} == {"Figtree", "Young Serif"}
    style = profile / "style.next"
    assert sorted(p.name for p in style.iterdir()) == ["cover-letter.template.html", "cv.template.html", "fonts", "source.pdf",
                                                      "style.json", "template.json"]
    manifest = templates.manifest(style / "cv.template.html")
    assert manifest.max_pages == 1 and manifest.columns.side  # a one page CV with a side column
    assert set(manifest.fonts) <= {p.name for p in (style / "fonts").iterdir()}
    assert templates.assets(style / "cv.template.html")["fonts"]
    assert html_guard.template_problems((style / "cv.template.html").read_text(), manifest) == []
    assert html_guard.template_problems((style / "cover-letter.template.html").read_text(), manifest, "letter") == []
    assert (style / "source.pdf").read_bytes() == (STYLES / "html-word-two-column.pdf").read_bytes()
    assert not [p for p in profile.iterdir() if p.name != "style.next"]  # nothing staged is left


def test_a_template_that_fails_the_stress_renders_even_after_the_extra_round_is_failed_and_writes_nothing(tmp_path):
    stylist = Stylist(cv_round(BIG), *[cv_only(BIG)] * 7, letter_round())  # up to the cap of rounds, then the extra one
    result, profile = _build(tmp_path, "html-word-two-column", stylist)
    assert result["state"] == "failed"
    assert any("fewer" in p and "pages" in p for p in result["problems"])
    assert list(profile.iterdir()) == []


def test_a_built_style_is_what_compile_prints_a_tailored_application_in(tmp_path, monkeypatch):
    icon = lambda t: t.replace("</style>", ICON_RULE + "\n</style>", 1)
    stylist = Stylist(cv_round(edit=icon), cv_only(edit=icon), letter_round())
    result, profile = _build(tmp_path, "scrubbed-altacv-icons-fr", stylist)
    assert result["state"] == "ready", result["problems"]
    (profile / "style.next").rename(profile / "style")  # chosen
    manifest = templates.manifest(profile / "style" / "cv.template.html")
    assert "email" in manifest.icons
    config = {"name": "Jane Doe", "location": "Aarhus", "cv_template": "profile/style/cv.template.html",
              "cover_letter_template": "profile/style/cover-letter.template.html"}
    (profile / "config.json").write_text(json.dumps(config))
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    out = tmp_path / "jobs" / "output" / "job"
    out.mkdir(parents=True)
    (out / "posting.json").write_text(json.dumps({"title": "Head of Finance", "company": "Globex", "location": "Aarhus"}))
    (out / "cv.html").write_text(cv_body.body((EXAMPLE / "cv.md").read_text(encoding="utf-8")), encoding="utf-8")
    (out / "cover_letter.html").write_text(style_preview.sample_letter((EXAMPLE / "cv.md").read_text(encoding="utf-8")), encoding="utf-8")
    compiled = {r["file"]: r for r in compile_cmd._compile_core("job", jobs_dir=tmp_path / "jobs")["results"]}
    assert compiled["cv.html"]["status"] == "compiled", compiled["cv.html"]
    assert compiled["cover_letter.html"]["status"] == "compiled", compiled["cover_letter.html"]
    for pdf in ("cv.pdf", "cover_letter.pdf"):
        assert font_names(out / pdf) == {"Figtree-Regular"}  # the built fonts (the stand-in download's file), not a fallback
    assert path_count(out / "cv.pdf") > 0  # the icon the template draws from /icons/email.svg



@pytest.mark.parametrize("extra", ["", "h2::first-letter { font-size: 140%; }", "h2 { letter-spacing: 0.3em; }"])
def test_a_print_with_the_side_column_on_the_wrong_side_is_found_whatever_its_headings_look_like(tmp_path, extra):
    """#242: a drop cap or wide letter-spacing prints a heading in pieces; the check still finds it."""
    style = style_extract.extract(STYLES / "latex-sidebar.pdf")  # side column on the left
    body = ('<header class="cv-header"><h1>Ada Lovelace</h1></header><h2>Education</h2><p>' + "Studied things. " * 8
            + "</p><h2>Skills</h2><p>Python, SQL</p><h2>Languages</h2><p>English</p>")
    template = ('<!DOCTYPE html><html lang="<<lang>>"><head><meta charset="utf-8"><style>@page { size: A4; margin: 0 } '
                "body { margin: 40pt; display: grid; grid-template-columns: 1fr 150pt; font-family: serif } "
                ".cv-header { grid-column: 1 / -1 } .photo { width: 1pt } " + extra + "</style></head><body><<body>></body></html>")
    pdf, placed, _ = compile_cmd.print_page(body, template, EXAMPLE / "cv.template.html", "en", tmp_path, "r",
                                            columns=templates.Columns(side=["skills", "languages"]))
    problems = style_build.column_problems(style, style_extract.extract(pdf), placed)
    assert any('"Skills"' in p for p in problems) and any('"Languages"' in p for p in problems), problems



@pytest.mark.parametrize("css", ["border-radius: 50%; background: #ccc", "border-radius: 12pt; background: #ccc",
                                 "border-radius: 50%; border: 3pt solid #999", "background: #ccc"])
def test_a_box_drawn_where_the_photo_is_is_found_whatever_its_corners(tmp_path, css):
    """#246: a round or rounded box prints as a path of many segments (no kind); it is found all the same."""
    body = ('<header class="cv-header"><h1>Ada Lovelace</h1></header><h2>Education</h2><p>'
            + "Studied things at a university in a city. " * 30 + "</p>")
    template = ('<!DOCTYPE html><html lang="<<lang>>"><head><meta charset="utf-8"><style>@page { size: A4; margin: 0 } '
                'body { margin: 40pt } .photo { width: 1pt } .cv-header::before { content: ""; display: block; '
                "width: 98pt; height: 98pt; " + css + " }</style></head><body><<body>></body></html>")
    pdf = compile_cmd.print_page(body, template, EXAMPLE / "cv.template.html", "en", tmp_path, "r")[0]
    style = {"photo": {"page": 1, "bbox": [40.0, 40.0, 138.0, 138.0], "shape": "rect"}}
    assert style_build.photo_box_problems(style, style_extract.painted(pdf))
