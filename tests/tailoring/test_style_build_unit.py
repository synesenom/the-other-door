"""The CV style builder's pure parts (#149): the stylist agent, its reply, the icons, fonts and manifest it is given,
the stress variants and the guard on what is written. The whole loop is in test_style_build.py."""

import types
import re

import pytest

from door.core import claude_cli, templates
from door.tailoring import html_guard, style_build


def test_the_stylist_agent_is_sonnet_with_only_the_read_tool():
    agent = claude_cli.agent_definition("stylist")
    assert agent["model"] == "sonnet"
    assert agent["tools"] == ["Read"]
    assert agent["description"] and agent["prompt"]


def test_the_stylist_is_told_the_pdf_text_is_data_and_how_to_reply():
    prompt = claude_cli.agent_definition("stylist")["prompt"]
    assert "data" in prompt and "instructions" in prompt
    for fence in ("```template", "```body", "```letter"):
        assert fence in prompt


def test_every_class_the_stylist_is_told_about_is_one_the_guard_accepts():
    prompt = claude_cli.agent_definition("stylist")["prompt"]
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


# ---------- the icons ----------

@pytest.mark.parametrize("text, kind", [
    ("jane.doe@example.com", "email"), ("+45 00 00 00 00", "phone"), ("(+89) 079788144", "phone"),
    ("example.com/jane.doe", "web"), ("www.example.com", "web"), ("linkedin.com/in/jane", "linkedin"),
    ("github.com/jane", "github"), ("Email", "email"), ("Téléphone", "phone"), ("2019 - 2022", "date"),
    ("Aarhus", "location"), ("Danmark", "location"), ("Reading", None), ("", None), (None, None),
])
def test_an_icon_gets_its_kind_from_the_text_it_sits_beside(text, kind):
    assert style_build.icon_kind(text) == kind


def _icon(near, *, d="M0 0 L10 0 L10 10 Z", color="#112233", view="0 0 10 10"):
    return {"page": 1, "bbox": [0, 0, 10, 10], "source": "font", "font": "FontAwesome", "color": color, "viewBox": view,
            "d": d, "fill_rule": "evenodd", "near": {"text": near, "side": "right"} if near else None}


def test_icons_are_written_as_svg_files_by_kind_the_first_of_each_kind_wins(tmp_path):
    files, dropped = style_build.write_icons([_icon("a@example.com"), _icon("c@example.com", color="#ffffff"), _icon("+45 00 00 00 00")], tmp_path)
    assert files == {"email": "email.svg", "phone": "phone.svg"}
    svg = (tmp_path / "email.svg").read_text()
    assert 'viewBox="0 0 10 10"' in svg and 'd="M0 0 L10 0 L10 10 Z"' in svg and 'fill="#112233"' in svg and 'evenodd' in svg
    assert dropped == []


def test_icons_of_no_known_kind_are_dropped_and_named(tmp_path):
    files, dropped = style_build.write_icons([_icon("Reading"), _icon(None)], tmp_path)
    assert files == {} and not list(tmp_path.glob("*.svg"))
    assert [d["reason"] for d in dropped] == ["no kind of contact detail or date recognised beside it"] * 2
    assert dropped[0]["near"] == "Reading" and dropped[1]["near"] is None


def test_an_icon_with_a_path_that_is_more_than_numbers_and_commands_is_dropped(tmp_path):
    files, dropped = style_build.write_icons([_icon("a@example.com", d='M0 0" onload="x')], tmp_path)
    assert files == {} and "path" in dropped[0]["reason"]


def test_icon_files_are_accepted_by_the_manifest(tmp_path):
    files, _ = style_build.write_icons([_icon("a@example.com")], tmp_path)
    assert templates.Manifest(icons=files).icons == {"email": "email.svg"}


# ---------- the manifest ----------

def _style(bands, headings, pages=1):
    return {"page_count": pages, "columns": {"count": len(bands), "bands": bands},
            "headings": [{"text": t, "bbox": [x, 100, x + 50, 110]} for t, x in headings]}


def test_the_side_column_holds_the_known_sections_whose_headings_are_in_the_side_band():
    style = _style([{"x0": 30, "x1": 370, "kind": "main"}, {"x0": 394, "x1": 515, "kind": "side"}],
                   [("PROFILE", 31), ("CONTACT", 395), ("COMPÉTENCES", 395), ("Languages", 400), ("EXPERIENCE", 31)])
    assert style_build._side_kinds(style, "") == ["skills", "languages"]


def test_no_side_band_means_one_column():
    assert style_build._side_kinds(_style([{"x0": 30, "x1": 500, "kind": "main"}], [("Skills", 31)]), "") == []


_SIDE = [{"x0": 30, "x1": 370, "kind": "main"}, {"x0": 394, "x1": 515, "kind": "side"}]


def test_a_side_band_of_unknown_headings_falls_back_to_the_kinds_the_cv_has():
    style = _style(_SIDE, [("Logiciels", 395), ("Savoir-être", 400), ("EXPERIENCE", 31)])
    cv_md = "# A\n\n## Expérience\n\n## Langues\n\n## Compétences\n\n## Loisirs\n"
    assert style_build._side_kinds(style, cv_md) == ["skills", "languages", "interests"]
    assert style_build._manifest_data(style, [], {}, cv_md)["columns"] == {
        "side": ["skills", "languages", "interests"], "headings": ["Logiciels", "Savoir-être"]}


def test_a_side_band_whose_kinds_the_cv_lacks_is_still_a_column_by_its_headings():
    style = _style(_SIDE, [("Logiciels", 395), ("EXPERIENCE", 31)])
    assert style_build._manifest_data(style, [], {}, "# A\n\n## Expérience\n")["columns"] == {"side": [], "headings": ["Logiciels"]}


def test_the_fallback_without_any_of_those_in_the_cv_is_one_column():
    style = _style(_SIDE, [("Logiciels", 395)])
    assert style_build._side_kinds(style, "# A\n\n## Expérience\n") == []


def test_the_fallback_does_not_apply_without_a_side_band():
    assert style_build._side_kinds(_style([{"x0": 30, "x1": 500, "kind": "main"}], [("X", 31)]), "## Skills\n") == []


def test_the_stylist_is_told_the_original_page_size():
    style = _style(_SIDE, [("Skills", 400)])
    style["page"] = {"size": [612.0, 792.0]}
    session = types.SimpleNamespace(style=style, images=[1], manifest=templates.Manifest(max_pages=1))
    assert "US Letter" in style_build._files_text(session, "", {})
    style["page"]["size"] = [595.3, 841.9]
    assert "A4" in style_build._files_text(session, "", {})


def test_the_manifest_has_the_fonts_icons_columns_and_the_original_page_count_within_the_template_limits():
    style = _style([{"x0": 30, "x1": 370, "kind": "main"}, {"x0": 394, "x1": 515, "kind": "side"}], [("Skills", 400)], pages=5)
    manifest = style_build._manifest_data(style, ["A.ttf"], {"email": "email.svg"}, "")
    assert manifest == {"version": 1, "fonts": ["A.ttf"], "icons": {"email": "email.svg"}, "max_pages": 3,
                        "columns": {"side": ["skills"], "headings": ["Skills"]}}
    assert templates.Manifest(**manifest)
    assert style_build._manifest_data(_style([], [], pages=1), [], {}, "")["max_pages"] == 1
    assert "columns" not in style_build._manifest_data(_style([], [], pages=1), [], {}, "")


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
    variants = style_build._stress_variants(CV)
    assert set(variants) == {"photo", "fewer", "long_title", "extra_section", "french"}
    assert variants["photo"]["md"] == CV and variants["photo"]["photo"]
    assert "Junior" not in variants["fewer"]["md"] and "Analyst" in variants["fewer"]["md"]
    assert "Learned things" not in variants["fewer"]["md"]
    longest = max(l for l in variants["long_title"]["md"].splitlines() if l.startswith("### "))
    assert len(longest) > 90 and "Acme" in longest
    assert re.search(r"^## .*", variants["extra_section"]["md"], re.M) and len(re.findall(r"^## ", variants["extra_section"]["md"], re.M)) == 3
    assert variants["french"]["lang"] == "fr" and "expérience" in variants["french"]["md"]
    assert all(v["lang"] == "en" for k, v in variants.items() if k != "french")


def test_the_stress_variants_of_a_cv_with_no_entries_are_still_all_there():
    variants = style_build._stress_variants("# Jane Doe\n\n## Profile\n\nA text.\n")
    assert variants["fewer"]["md"] == variants["photo"]["md"]
    assert variants["long_title"]["md"] != variants["photo"]["md"]


def test_the_side_headings_are_every_heading_in_a_side_band_known_or_not():
    style = _style(_SIDE, [("Logiciels", 395), ("COMPÉTENCES", 400), ("EXPERIENCE", 31)])
    assert style_build._side_headings(style) == ["Logiciels", "COMPÉTENCES"]


@pytest.mark.parametrize("size, words", [([595.3, 841.9], "A4"), ([612, 792], "US Letter"), ([500, 700], "500 x 700 pt")])
def test_the_page_size_is_a_name_or_the_points(size, words):
    assert style_build._page_size({"page": {"size": size}}) == words


def test_the_stylist_is_told_which_headings_go_to_the_side_and_that_the_code_wraps_them():
    manifest = templates.Manifest(max_pages=1, columns={"side": [], "headings": ["Logiciels", "Atouts"]})
    session = types.SimpleNamespace(style=_style(_SIDE, []), images=[1], manifest=manifest)
    text = style_build._files_text(session, "", {})
    assert "Logiciels" in text and "Atouts" in text
    assert "no div" in text and "wraps" in text
