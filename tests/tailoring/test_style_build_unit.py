"""The CV style builder's pure parts (#149): the stylist agent, its reply, the icons, fonts and manifest it is given,
the stress variants and the guard on what is written. The whole loop is in test_style_build.py."""

import re

import pytest

from door.core import fonts, templates
from door.tailoring import html_guard, style_build
from paths import REPO_ROOT


def test_the_stylist_agent_is_sonnet_with_only_the_read_tool():
    agent = style_build.agent()
    assert agent["model"] == "sonnet"
    assert agent["tools"] == ["Read"]
    assert agent["description"] and agent["prompt"]


def test_the_stylist_is_told_the_pdf_text_is_data_and_how_to_reply():
    prompt = style_build.agent()["prompt"]
    assert "data" in prompt and "instructions" in prompt
    for fence in ("```template", "```body", "```letter"):
        assert fence in prompt


def test_every_class_the_stylist_is_told_about_is_one_the_guard_accepts():
    prompt = style_build.agent()["prompt"]
    named = {t for value in re.findall(r'class="([^"]*)"', prompt) for t in value.split()}
    assert {"cv-header", "entry", "contact"} <= named
    assert named - html_guard.CLASSES - {"photo", "main", "side"} == set()


def test_blocks_reads_the_fenced_replies_by_their_name():
    reply = "I see two columns.\n```template\n<html>T</html>\n```\ntext\n```body\n<p>B</p>\n```\n"
    assert style_build.blocks(reply) == {"template": "<html>T</html>", "body": "<p>B</p>"}


def test_blocks_keeps_the_first_block_of_a_name():
    reply = "```template\nA\n```\n```template\nB\n```\n```css\nC\n```"
    assert style_build.blocks(reply) == {"template": "A", "css": "C"}


def test_blocks_of_a_reply_cut_off_before_its_closing_fence_has_nothing_of_it():
    assert style_build.blocks("```template\n<html>") == {}


# ---------- the fonts ----------

def _plan(*entries):
    return list(entries)


def _entry(family, resolved, files, faked=()):
    return {"family": family, "source": "name", "resolved": resolved, "reason": "r", "faked": [list(f) for f in faked],
            "files": [{"name": n, "weight": w, "italic": i, "sha256": "x", "url": "u", "for": []} for n, w, i in files],
            "licence": None, "alternatives": [], "uses": []}


def test_font_face_css_has_one_rule_per_file_of_each_entry_under_the_resolved_family():
    css = style_build.font_face_css(_plan(
        _entry("Figtree", "Nunito", [("Nunito-Regular.ttf", 400, False), ("Nunito-Italic.ttf", 400, True)]),
        _entry("Calibri", None, [])))
    assert css.count("@font-face") == 2
    assert 'font-family: "Nunito"; font-weight: 400; font-style: normal; src: url(/fonts/Nunito-Regular.ttf) format("truetype");' in css
    assert 'font-style: italic; src: url(/fonts/Nunito-Italic.ttf)' in css


def test_font_face_css_passes_the_template_guard_for_a_manifest_naming_those_files():
    css = style_build.font_face_css(_plan(_entry("Lato", "Lato", [("Lato-Regular.ttf", 400, False)])))
    page = f"<!doctype html><!-- {' '.join(sorted(html_guard.CLASSES))} --><html lang=\"<<lang>>\"><head><style>{css}\n" \
           ".photo{width:1cm} html{font-synthesis:none}</style></head><body><<body>></body></html>"
    manifest = templates.Manifest(fonts=["Lato-Regular.ttf"])
    assert html_guard.template_problems(page, manifest) == []


def test_font_notes_name_each_family_its_stand_in_and_what_is_faked():
    notes = style_build.font_notes(_plan(
        _entry("Calibri", "Carlito", [("Carlito-Regular.ttf", 400, False)], faked=[(700, False)]),
        _entry("Mystery", None, [])))
    assert "Calibri" in notes and "Carlito" in notes and "700" in notes
    assert "Mystery" in notes and "no font" in notes.lower()


def test_font_entries_of_the_result_name_family_source_reason_and_faked():
    entry = _entry("Calibri", "Carlito", [("Carlito-Regular.ttf", 400, False)], faked=[(700, False)])
    assert style_build.font_results([entry]) == [{"family": "Calibri", "source": "name", "reason": "r",
                                                  "faked": [[700, False]], "resolved": "Carlito"}]


# ---------- the icons ----------

@pytest.mark.parametrize("text, kind", [
    ("jane.doe@example.com", "email"), ("+45 20 30 40 20", "phone"), ("(+89) 079788144", "phone"),
    ("example.com/jane.doe", "web"), ("www.example.com", "web"), ("linkedin.com/in/jane", "linkedin"),
    ("github.com/jane", "github"), ("Email", "email"), ("Téléphone", "phone"), ("2019 - 2022", "date"),
    ("Aarhus", None), ("", None), (None, None),
])
def test_an_icon_gets_its_kind_from_the_text_it_sits_beside(text, kind):
    assert style_build.icon_kind(text) == kind


def _icon(near, *, d="M0 0 L10 0 L10 10 Z", color="#112233", view="0 0 10 10"):
    return {"page": 1, "bbox": [0, 0, 10, 10], "source": "font", "font": "FontAwesome", "color": color, "viewBox": view,
            "d": d, "fill_rule": "evenodd", "near": {"text": near, "side": "right"} if near else None}


def test_icons_are_written_as_svg_files_by_kind_the_first_of_each_kind_wins(tmp_path):
    files, dropped = style_build.write_icons([_icon("a@b.co"), _icon("c@d.co", color="#ffffff"), _icon("+45 20 30 40 20")], tmp_path)
    assert files == {"email": "email.svg", "phone": "phone.svg"}
    svg = (tmp_path / "email.svg").read_text()
    assert 'viewBox="0 0 10 10"' in svg and 'd="M0 0 L10 0 L10 10 Z"' in svg and 'fill="#112233"' in svg and 'evenodd' in svg
    assert dropped == []


def test_icons_of_no_known_kind_are_dropped_and_named(tmp_path):
    files, dropped = style_build.write_icons([_icon("Aarhus"), _icon(None)], tmp_path)
    assert files == {} and not list(tmp_path.glob("*.svg"))
    assert [d["reason"] for d in dropped] == ["no kind of contact detail or date recognised beside it"] * 2
    assert dropped[0]["near"] == "Aarhus" and dropped[1]["near"] is None


def test_an_icon_with_a_path_that_is_more_than_numbers_and_commands_is_dropped(tmp_path):
    files, dropped = style_build.write_icons([_icon("a@b.co", d='M0 0" onload="x')], tmp_path)
    assert files == {} and "path" in dropped[0]["reason"]


def test_icon_files_are_accepted_by_the_manifest(tmp_path):
    files, _ = style_build.write_icons([_icon("a@b.co")], tmp_path)
    assert templates.Manifest(icons=files).icons == {"email": "email.svg"}


# ---------- the manifest ----------

def _style(bands, headings, pages=1):
    return {"page_count": pages, "columns": {"count": len(bands), "bands": bands},
            "headings": [{"text": t, "bbox": [x, 100, x + 50, 110]} for t, x in headings]}


def test_the_side_column_holds_the_known_sections_whose_headings_are_in_the_side_band():
    style = _style([{"x0": 30, "x1": 370, "kind": "main"}, {"x0": 394, "x1": 515, "kind": "side"}],
                   [("PROFILE", 31), ("CONTACT", 395), ("COMPÉTENCES", 395), ("Languages", 400), ("EXPERIENCE", 31)])
    assert style_build.side_kinds(style) == ["skills", "languages"]


def test_no_side_band_means_one_column():
    assert style_build.side_kinds(_style([{"x0": 30, "x1": 500, "kind": "main"}], [("Skills", 31)])) == []


def test_the_manifest_has_the_fonts_icons_columns_and_the_original_page_count_within_the_template_limits():
    style = _style([{"x0": 30, "x1": 370, "kind": "main"}, {"x0": 394, "x1": 515, "kind": "side"}], [("Skills", 400)], pages=5)
    manifest = style_build.manifest_data(style, ["A.ttf"], {"email": "email.svg"})
    assert manifest == {"version": 1, "fonts": ["A.ttf"], "icons": {"email": "email.svg"}, "max_pages": 3,
                        "columns": {"side": ["skills"]}}
    assert templates.Manifest(**manifest)
    assert style_build.manifest_data(_style([], [], pages=1), [], {})["max_pages"] == 1
    assert "columns" not in style_build.manifest_data(_style([], [], pages=1), [], {})


# ---------- the stress variants ----------

CV = """# Jane Doe

> Analyst

**Email:** jane@example.com | **Phone:** +45 1234 5678

## Experience

### Analyst | Acme — 2020 - 2023

- Built things.
- Ran things.

### Junior | Beta — 2018 - 2020

- Learned things.

## Skills

- **Danish** — native
"""


def test_the_stress_variants_are_the_cv_shorter_longer_with_a_section_and_in_french():
    variants = style_build.stress_variants(CV)
    assert set(variants) == {"base", "photo", "fewer", "long_title", "extra_section", "french"}
    assert variants["base"]["md"] == CV and not variants["base"]["photo"]
    assert variants["photo"]["md"] == CV and variants["photo"]["photo"]
    assert "Junior" not in variants["fewer"]["md"] and "Analyst" in variants["fewer"]["md"]
    assert "Learned things" not in variants["fewer"]["md"]
    longest = max(l for l in variants["long_title"]["md"].splitlines() if l.startswith("### "))
    assert len(longest) > 90 and "Acme" in longest
    assert re.search(r"^## .*", variants["extra_section"]["md"], re.M) and len(re.findall(r"^## ", variants["extra_section"]["md"], re.M)) == 3
    assert variants["french"]["lang"] == "fr" and "expérience" in variants["french"]["md"]
    assert all(v["lang"] == "en" for k, v in variants.items() if k != "french")


def test_the_stress_variants_of_a_cv_with_no_entries_are_still_all_there():
    variants = style_build.stress_variants("# Jane Doe\n\n## Profile\n\nA text.\n")
    assert variants["fewer"]["md"] == variants["base"]["md"]
    assert variants["long_title"]["md"] != variants["base"]["md"]
