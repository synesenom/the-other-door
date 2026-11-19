"""The CV style builder's pure parts (#149): the stylist agent, its reply, the icons, fonts and manifest it is given,
the stress variants and the guard on what is written. The whole loop is in test_style_build.py."""

import types
import re

import pytest

from door import i18n
from door.core import claude_cli, templates
from door.render import html_guard, pdf_render
from door.style import style_build
from style_build_utils import STYLES
from style_structure_utils import extract_with, recorded


def test_the_stylist_agent_is_sonnet_with_only_the_read_tool():
    agent = claude_cli.agent_definition("stylist")
    assert agent["model"] == "sonnet"
    assert agent["tools"] == ["Read"]
    assert agent["description"] and agent["prompt"]


def test_the_stylist_is_told_the_pdf_text_is_data_and_how_to_reply():
    prompt = claude_cli.agent_definition("stylist")["prompt"]
    assert "data" in prompt and "instructions" in prompt
    for fence in ("```template", "```cv", "```letter"):
        assert fence in prompt


def test_every_class_the_stylist_is_told_about_is_one_the_guard_accepts():
    prompt = claude_cli.agent_definition("stylist")["prompt"]
    named = {t for value in re.findall(r'class="([^"]*)"', prompt) for t in value.split()}
    assert {"cv-header", "entry", "contact"} <= named
    assert named - html_guard.CLASSES - {"photo", "main", "side", "label"} == set()


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
            "headings": [{"text": t, "bbox": [x, 100, x + 50, 110], "kind": i18n.cv_section_kind(t, templates.SECTION_KINDS) or "other",
                          "band": next((b["kind"] for b in bands if b["x0"] - 2 <= x + 25 <= b["x1"] + 2), None)}
                         for t, x in headings]}


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
    assert set(variants) == {"photo", "fewer", "long_title", "extra_section", "french", "shapes"}
    assert variants["photo"]["md"] == CV and variants["photo"]["photo"]
    assert "Junior" not in variants["fewer"]["md"] and "Analyst" in variants["fewer"]["md"]
    assert "Learned things" not in variants["fewer"]["md"]
    longest = max(l for l in variants["long_title"]["md"].splitlines() if l.startswith("### "))
    assert len(longest) > 90 and "Acme" in longest
    assert re.search(r"^## .*", variants["extra_section"]["md"], re.M) and len(re.findall(r"^## ", variants["extra_section"]["md"], re.M)) == 3
    assert variants["french"]["lang"] == "fr" and "expérience" in variants["french"]["md"]
    assert all(v["lang"] == "en" for k, v in variants.items() if k != "french")


def test_the_shapes_variant_holds_every_shape_of_the_vocabulary_whatever_the_cv():
    from door.style import cv_body
    from door.render import html_guard
    md = style_build._stress_variants(CV)["shapes"]["md"]
    html = cv_body.body(md)
    assert html_guard.unsafe(html) == []
    for kind in ("phone", "email", "web", "location", "linkedin", "github"):
        assert f'<span class="{kind}">' in html
    for part in ("role", "org", "dates", "place", "sep"):
        assert f'<span class="{part}">' in html
    assert 'level level-5' in html and 'level level-1' in html and "<ol>" in html and "<ul>" in html
    assert all(tag in html for tag in ("<strong>", "<em>", "<a href"))
    assert cv_body.body(md).count("<h1>") == 1 and cv_body.body(CV).count("<h1>") == 1


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


# ---------- the columns (#242) ----------

def _extract(name):
    return extract_with(STYLES / f"{name}.pdf", recorded(name))


def _placed(main, side):
    return ('<header class="cv-header"><h1>A B</h1></header><div class="main">'
            + "".join(f"<h2>{h}</h2><p>x</p>" for h in main) + '</div><div class="side">'
            + "".join(f"<h2>{h}</h2><p>y</p>" for h in side) + "</div>")


def test_a_print_with_the_columns_where_the_original_has_them_has_no_column_problem():
    style = _extract("latex-sidebar")
    assert style_build.column_problems(style, style, _placed(["Education"], ["Skills", "Languages"])) == []


def test_a_print_with_the_columns_swapped_names_where_each_printed_and_where_it_belongs():
    # latex-sidebar has its side column on the left; html-word-two-column prints the same headings with it on the right
    problems = style_build.column_problems(_extract("latex-sidebar"), _extract("html-word-two-column"),
                                           _placed(["Education"], ["Skills", "Languages"]))
    side = [p for p in problems if "Skills" in p or "Languages" in p]
    assert len(side) == 2 and all("side column" in p and "on the left" in p for p in side)
    assert any("Education" in p and "main column" in p and "on the right" in p for p in problems)


def test_a_print_with_the_side_on_the_right_of_a_cv_with_equal_columns_names_the_misplaced_headings():
    # html-equal-columns has its side (skills, education, languages) in the left column of two of the same width
    problems = style_build.column_problems(_extract("html-equal-columns"), _extract("html-word-two-column"),
                                           _placed(["Experience"], ["Skills", "Languages"]))
    side = [p for p in problems if "Skills" in p or "Languages" in p]
    assert len(side) == 2 and all("side column" in p and "on the left" in p for p in side)


def test_a_body_with_no_side_column_or_an_original_with_none_has_no_column_problem():
    one = _extract("latex-classic")
    assert style_build.column_problems(_extract("latex-sidebar"), _extract("html-word-two-column"), "<h2>Skills</h2><p>x</p>") == []
    assert style_build.column_problems(one, one, _placed(["Education"], ["Skills"])) == []


def test_the_text_of_a_two_column_cv_is_given_column_by_column_on_each_page():
    text = style_build.original_text(_extract("scrubbed-pages-sidebar-fr"), STYLES / "scrubbed-pages-sidebar-fr.pdf")
    labels = [line for line in text.splitlines() if line.startswith("[page 1")]
    assert labels == ["[page 1, across the page]", "[page 1, side column, on the left]", "[page 1, main column, on the right]"]
    page2_side, page2_main = text.split("[page 2, side column, on the left]")[1].split("[page 2, main column, on the right]")
    assert "Nid Couleur Jardin Silence" in page2_main and "Nid Couleur Jardin Silence" not in page2_side
    assert "Jardin cou Parfumerie" in page2_side
    assert "ATROTTOIR ALOIN" in text.splitlines()  # a heading's larger first letter stays in its word


def test_the_text_of_a_one_column_cv_is_its_lines_with_no_column_labels():
    text = style_build.original_text(_extract("latex-classic"), STYLES / "latex-classic.pdf")
    whole = "\n".join(pdf_render.page_texts(STYLES / "latex-classic.pdf"))
    assert "[page" not in text
    assert text.split() == whole.split()


@pytest.mark.parametrize("name", ["scrubbed-pages-header-en", "scrubbed-altacv-icons-fr"])
def test_the_text_of_a_cv_leaves_out_its_icon_glyphs(name):
    # an icon drawn from an icon font reads back as a stray character ("!"): in text.txt the stylist would copy it
    # into the sample body, and the rebuild printed it where the icon was (#248)
    # A lone bullet in the icon font (altacv's last level dot "○") is not marked an icon, but it is one of its glyphs.
    style = _extract(name)
    icon_fonts = {r["font"] for r in style["runs"] if r["icon"]}
    glyphs = {c for r in style["runs"] if r["font"] in icon_fonts for c in r["text"] if not c.isspace()}
    text = style_build.original_text(style, STYLES / f"{name}.pdf")
    lines = [line for line in text.splitlines() if not line.startswith("[page ")]
    assert glyphs and not glyphs & set("".join(lines))
    assert "petit." in text.splitlines() or name != "scrubbed-pages-header-en"


def test_a_sample_body_that_puts_text_of_the_originals_main_column_under_a_side_heading_is_named():
    style = _extract("scrubbed-pages-sidebar-fr")
    columns = templates.Columns(side=[], headings=["AFONTAINE ANUIT"])
    line = "<p>Nid Couleur Jardin Silence: UNE&amp;FRUIT 4888, Feuillage Cabane Aquarelle Dimanche</p>"
    good = "<h2>LEUNE YAUTOMNE</h2>" + line + "<h2>AFONTAINE ANUIT</h2><p>y</p>"
    bad = "<h2>LEUNE YAUTOMNE</h2><p>x</p><h2>AFONTAINE ANUIT</h2>" + line
    assert style_build.body_column_problems(style, good, columns) == []
    problems = style_build.body_column_problems(style, bad, columns)
    assert len(problems) == 1 and "Nid Couleur Jardin Silence" in problems[0] and "main column" in problems[0]


def test_the_stylist_is_told_on_which_side_the_side_column_is_and_that_div_main_comes_first():
    manifest = templates.Manifest(max_pages=1, columns={"side": ["skills"], "headings": []})
    session = types.SimpleNamespace(style=_extract("latex-sidebar"), images=[1], manifest=manifest)
    text = style_build._files_text(session, "", {})
    assert "on the left" in text and "div.main first" in text


# ---------- the photo's place with no photo (#246) ----------

_PHOTO = {"page": 1, "bbox": [35.0, 159.0, 133.0, 297.0], "shape": "rect"}


def _shape(bbox, fill="#b0b0b0", stroke=None, kind="box"):
    return {"kind": kind, "bbox": bbox, "fill": fill, "stroke": stroke}


def _pages(*paths, background=None, page=1):
    """`style_extract.painted` of a print: `paths` on page `page`, the other pages blank."""
    return [{"background": background, "paths": list(paths) if n == page else []} for n in range(1, max(page, 1) + 1)]


def test_a_print_with_no_photo_that_draws_a_box_where_the_original_s_photo_is_is_named():
    problems = style_build.photo_box_problems({"photo": _PHOTO}, _pages(_shape([36, 160, 132, 296])))
    assert len(problems) == 1 and "img.photo" in problems[0] and "x 36-132" in problems[0]


def test_a_frame_drawn_round_the_photo_s_place_is_named_too():
    assert style_build.photo_box_problems({"photo": _PHOTO}, _pages(_shape([33, 157, 135, 299], fill=None, stroke="#888888")))


def test_a_disc_or_a_rounded_box_a_path_of_no_kind_is_named_too():
    assert style_build.photo_box_problems({"photo": _PHOTO}, _pages(_shape([36, 160, 132, 296], kind=None)))


def test_a_side_band_a_rule_or_a_box_elsewhere_is_not_the_photo_s_box():
    paths = [_shape([0, 0, 143, 842], fill="#eeeeee"),  # a side band's background, far larger than the photo
             _shape([35, 300, 133, 301]),  # a rule under the photo's place
             _shape([200, 160, 298, 298])]  # a box beside it
    assert style_build.photo_box_problems({"photo": _PHOTO}, _pages(*paths)) == []
    assert style_build.photo_box_problems({"photo": _PHOTO}, _pages(_shape([36, 160, 132, 296]), page=2)) == []


def test_a_box_filled_with_the_colour_under_it_draws_nothing_to_see():
    page = _shape([36, 160, 132, 296], fill="#ffffff")
    assert style_build.photo_box_problems({"photo": _PHOTO}, _pages(page, background="#ffffff")) == []
    band = [_shape([0, 0, 180, 842], fill="#20304a"), _shape([36, 160, 132, 296], fill="#20304a")]
    assert style_build.photo_box_problems({"photo": _PHOTO}, _pages(*band)) == []
    framed = _shape([36, 160, 132, 296], fill="#ffffff", stroke="#888888")  # its frame shows
    assert style_build.photo_box_problems({"photo": _PHOTO}, _pages(framed, background="#ffffff"))


def test_an_original_with_no_photo_has_no_photo_box_problem():
    assert style_build.photo_box_problems({"photo": None}, _pages(_shape([36, 160, 132, 296]))) == []


def _run(text, bbox, page=1, size=10.0):
    return {"page": page, "text": text, "bbox": bbox, "size": size}


def test_a_heading_printed_in_pieces_is_still_found_where_it_printed():
    # a drop cap (`S` + `kills`) and wide letter-spacing (`L a n g`...) print a heading as several runs on one line
    style = _extract("latex-sidebar")  # side column on the left, x 7-129
    render = {"runs": [_run("S", [400, 100, 408, 112], size=14), _run("kills", [408, 102, 440, 112]),
                       *[_run(c, [400 + 8 * i, 200, 406 + 8 * i, 210]) for i, c in enumerate("Languages")]]}
    problems = style_build.column_problems(style, render, _placed([], ["Skills", "Languages"]))
    assert len(problems) == 2 and all("other column" in p for p in problems)


def test_a_heading_printed_across_both_columns_is_named_as_such():
    style = _extract("latex-sidebar")
    render = {"runs": [_run("Skills", [60, 100, 300, 112])]}  # from the side band into the main one
    assert style_build._band_of([60, 100, 300, 112], style["columns"]["bands"]) is None
    problems = style_build.column_problems(style, render, _placed([], ["Skills"]))
    assert len(problems) == 1 and "across both columns" in problems[0]


def test_a_band_between_two_others_is_in_the_middle():
    bands = [{"x0": 10, "x1": 100, "kind": "side"}, {"x0": 120, "x1": 400, "kind": "main"}, {"x0": 420, "x1": 580, "kind": "side"}]
    assert [style_build._where(b, bands) for b in bands] == [
        "side column, on the left", "main column, in the middle", "side column, on the right"]


def test_a_print_with_no_text_read_back_has_no_column_problem():
    assert style_build.column_problems(_extract("latex-sidebar"), {}, _placed(["Education"], ["Skills"])) == []


def test_a_line_the_pdf_prints_with_a_ligature_is_found_in_the_body_spelt_out():
    bands = [{"x0": 20, "x1": 160, "kind": "side"}, {"x0": 180, "x1": 575, "kind": "main"}]
    style = {"columns": {"bands": bands},
             "runs": [{"page": 1, "text": "Certi\ufb01ed scienti\ufb01c of\ufb01cer", "bbox": [30, 100, 150, 110], "size": 9.0}]}
    body = ('<header class="cv-header"><h1>A B</h1></header><h2>Experience</h2><p>Certified scientific officer</p>'
            "<h2>Skills</h2><p>Python</p>")
    problems = style_build.body_column_problems(style, body, templates.Columns(side=["skills"]))
    assert len(problems) == 1 and "side column of the original" in problems[0]


def test_side_kinds_fall_back_to_the_kinds_a_draft_recorded_on_own_titles():
    style = _style(_SIDE, [("Logiciels", 395), ("EXPERIENCE", 31)])
    assert style_build._side_kinds(style, "# A\n\n## Mes outils <!-- kind: skills -->\n\n## Parcours\n") == ["skills"]
