"""door.tailoring.style_extract: a CV PDF's style read as facts, on PDFs written by hand (#148)."""

import pytest

from pdf_utils import raw_pdf
from style_rules_utils import rules_extract

from door.tailoring import style_build, style_compare, style_extract


def read(tmp_path, content, **kwargs):
    path = tmp_path / "cv.pdf"
    path.write_bytes(raw_pdf(content, **kwargs))
    return rules_extract(path)


def text(font, size, x, y, s, color="0 0 0"):
    return f"BT /{font} {size} Tf {color} rg {x} {y} Td ({s}) Tj ET\n"


def body(n=60):
    """enough visible text that the document is not taken for a scan"""
    return "".join(text("F1", 10, 50, 600 - 12 * i, f"Plain line number {i} of the body text") for i in range(n // 6 + 3))


def run_of(style, word):
    return next(r for r in style["runs"] if word in r["text"])


def test_a_run_has_its_text_position_colour_and_page(tmp_path):
    style = read(tmp_path, text("F1", 12, 50, 700, "Hello", "0.8 0 0") + body(), size=(300, 800))
    run = run_of(style, "Hello")
    assert run["color"] == "#cc0000" and run["page"] == 1 and run["size"] == 12.0
    # the origin is the top left: the baseline at 700 of 800 is 100 from the top
    left, top, right, bottom = run["bbox"]
    assert 50 <= left < 52 and 85 < top < 100 and 100 <= bottom < 106 and right > left + 20
    assert style["page"]["size"] == [300.0, 800.0] and style["page_count"] == 1


def test_the_size_is_the_font_size_times_the_text_matrix(tmp_path):
    # Apple Pages writes a font size of 1 and scales in the matrix
    content = "BT /F1 1 Tf 16 0 0 16 50 700 Tm (Scaled) Tj ET\nBT /F1 12 Tf 50 650 Td (Plain) Tj ET\n" + body()
    style = read(tmp_path, content)
    assert run_of(style, "Scaled")["size"] == 16.0 and run_of(style, "Plain")["size"] == 12.0


@pytest.mark.parametrize("font,weight,italic,serif,fixed,family", [
    ("F1", 400, False, False, False, "Helvetica"), ("F2", 700, False, False, False, "Helvetica"),
    ("F3", 400, False, True, False, "Times"), ("F4", 400, False, False, True, "Courier"),
    ("F5", 400, True, False, False, "Helvetica"),
])
def test_a_run_has_the_facts_of_its_font(tmp_path, font, weight, italic, serif, fixed, family):
    style = read(tmp_path, text(font, 12, 50, 700, "Sample") + body())
    run = run_of(style, "Sample")
    assert (run["weight"], run["italic"], run["serif"], run["fixed"]) == (weight, italic, serif, fixed)
    assert run["family"] == family and run["embedded"] is False and run["rotated"] is False
    fonts = {f["font"]: f for f in style["fonts"]}
    assert fonts[run["font"]]["runs"] >= 1 and fonts[run["font"]]["chars"] >= 6


@pytest.mark.parametrize("name,weight,family", [
    ("ABCDEF+Lato-Light", 300, "Lato"), ("Figtree-SemiBold", 600, "Figtree"), ("Roboto-Black", 900, "Roboto"),
    ("Inter-ExtraBold", 800, "Inter"), ("Optima-Bold", 700, "Optima"), ("Arial-BoldMT", 700, "Arial"),
    ("Source Sans-Thin", 100, "Source Sans"),
])
def test_weight_and_family_come_from_the_font_name(name, weight, family):
    facts = style_extract.font_facts_from_name(name)
    assert facts["weight"] == weight and facts["family"] == family


def test_words_written_one_by_one_join_into_a_run_and_a_far_gap_does_not(tmp_path):
    # "Hel" + "lo" abut, "far" is a column away
    content = text("F1", 12, 50, 700, "Hel") + text("F1", 12, 50 + 18, 700, "lo") + text("F1", 12, 300, 700, "far") + body()
    style = read(tmp_path, content, size=(400, 800))
    texts = [r["text"] for r in style["runs"] if r["bbox"][1] < 110]
    assert texts == ["Hello", "far"]


def test_invisible_text_is_not_a_run(tmp_path):
    content = "BT /F1 12 Tf 3 Tr 50 700 Td (ocr layer) Tj 0 Tr ET\n" + body()
    assert not [r for r in read(tmp_path, content)["runs"] if "ocr" in r["text"]]


def test_the_result_has_a_version_and_the_page_count(tmp_path):
    style = read_pages(tmp_path, [body(), body()])
    assert style["version"] == 1 and style["page_count"] == 2


# ---------- nothing to copy ----------

def page_image(w=595, h=842):
    return {"Im1": (2, 2, bytes([200, 200, 200] * 4))}, f"q {w} 0 0 {h} 0 0 cm /Im1 Do Q\n"


def read_pages(tmp_path, pages, **kwargs):
    path = tmp_path / "cv.pdf"
    path.write_bytes(raw_pdf(pages, **kwargs))
    return rules_extract(path)


def test_a_scan_has_nothing_to_copy(tmp_path):
    images, draw = page_image()
    style = read_pages(tmp_path, draw, images=images)
    assert style["verdict"]["copyable"] is False and style["verdict"]["reason"] == "scan"
    assert "runs" not in style  # nothing else is read


def test_a_page_with_a_few_characters_is_a_scan_too(tmp_path):
    style = read(tmp_path, text("F1", 10, 50, 700, "Page 1"))
    assert style["verdict"] == {"copyable": False, "reason": "scan", "detail": style["verdict"]["detail"]}


def test_an_ocr_layer_over_a_page_image_is_a_scan(tmp_path):
    images, draw = page_image()
    ocr = "".join(f"BT /F1 10 Tf 3 Tr 50 {700 - 12 * i} Td (invisible recognised line number {i}) Tj ET\n" for i in range(20))
    style = read_pages(tmp_path, draw + ocr, images=images)
    assert style["verdict"]["reason"] == "scan"


def test_a_cv_with_text_and_one_font_is_copyable(tmp_path):
    style = read(tmp_path, body())
    assert style["verdict"] == {"copyable": True, "reason": "ok", "detail": ""}


def _linkedin_page(n, headings):
    out = "".join(text("F1", 12, 50, 760 - 40 * i, h) for i, h in enumerate(headings))
    out += "".join(text("F1", 10, 50, 600 - 12 * i, f"Some line {i} of this person's page") for i in range(8))
    return out + text("F1", 9, 260, 30, f"Page {n} of 2")


def test_a_linkedin_export_is_recognised_by_its_headings_and_page_footers(tmp_path):
    pages = [_linkedin_page(1, ["Contact", "Top Skills", "Languages"]), _linkedin_page(2, ["Summary", "Experience", "Education"])]
    verdict = read_pages(tmp_path, pages)["verdict"]
    assert verdict["copyable"] is False and verdict["reason"] == "linkedin"


def test_the_headings_without_the_page_footers_are_a_cv(tmp_path):
    pages = [_linkedin_page(1, ["Contact", "Top Skills", "Languages"])]
    pages = [p.replace("Page 1 of 2", "") for p in pages]
    assert read_pages(tmp_path, pages)["verdict"]["copyable"] is True


def test_the_footers_with_too_few_of_the_headings_are_a_cv(tmp_path):
    pages = [_linkedin_page(1, ["Summary", "Experience"]), _linkedin_page(2, ["Skills"])]
    assert read_pages(tmp_path, pages)["verdict"]["copyable"] is True


@pytest.mark.parametrize("name", ["cv.docx", "cv.txt", "cv.md", "CV.HTML", "cv.rtf", "cv.odt", "scan.PNG", "photo.jpeg", "cv"])
def test_a_file_that_is_not_a_pdf_has_no_layout(name):
    verdict = style_extract.not_pdf(name)
    assert verdict["copyable"] is False and verdict["reason"] == "not_pdf" and verdict["detail"]


def test_a_pdf_name_is_left_to_extract():
    assert style_extract.not_pdf("cv.pdf") is None and style_extract.not_pdf("CV.PDF") is None


# ---------- margins, bleed, background ----------

def block(x, top, bottom, size=10):
    """lines of body text from baseline `top` down to `bottom` (PDF y), at x"""
    n = int((top - bottom) / 14) + 1
    return "".join(text("F1", size, x, top - 14 * i, f"A line of the body text, number {i}, to read") for i in range(n))


def test_margins_are_the_space_around_the_text(tmp_path):
    margins = read_pages(tmp_path, [block(60, 780, 90), block(60, 780, 400)])["page"]["margins"]
    assert 59 <= margins["left"] <= 62 and 53 <= margins["top"] <= 57 and 90 <= margins["bottom"] <= 94
    assert 345 <= margins["right"] <= 355  # the longest line is about 185 wide


def test_a_page_number_in_the_foot_is_not_the_bottom_margin(tmp_path):
    plain = read_pages(tmp_path, [block(60, 780, 100), block(60, 780, 100)])["page"]["margins"]
    footed = read_pages(tmp_path, [block(60, 780, 100) + text("F1", 9, 290, 20, "3"),
                                   block(60, 780, 100) + text("F1", 9, 290, 20, "Page 2 of 2")])["page"]["margins"]
    assert footed["bottom"] == plain["bottom"]


def test_only_a_page_with_another_after_it_gives_the_bottom_margin(tmp_path):
    # a last page is as long as the text is: half empty says nothing about the margin the design keeps
    margins = read_pages(tmp_path, [block(60, 780, 100), block(60, 780, 500)])["page"]["margins"]
    assert 100 <= margins["bottom"] <= 108


def test_a_single_page_has_the_top_margin_as_its_bottom_one(tmp_path):
    margins = read(tmp_path, block(60, 780, 500))["page"]["margins"]
    assert margins["bottom"] == margins["top"]


def test_the_smallest_margin_of_any_page_counts(tmp_path):
    style = read_pages(tmp_path, [block(60, 780, 100), block(40, 780, 100)])
    assert 39 <= style["page"]["margins"]["left"] <= 42


def test_a_page_sized_fill_is_the_background_not_a_box(tmp_path):
    style = read(tmp_path, "0.95 0.9 0.8 rg 0 0 595 842 re f\n" + block(60, 780, 100))
    assert style["page"]["background"] == "#f2e6cc" and style["shapes"] == [] and style["page"]["bleed"] == []


def test_a_sidebar_to_the_edge_bleeds_that_side_and_is_a_box(tmp_path):
    style = read(tmp_path, "0.1 0.2 0.4 rg 0 0 150 842 re f\n" + block(180, 780, 100))
    assert style["page"]["bleed"] == ["left"] and style["page"]["background"] is None
    (box,) = style["shapes"]
    assert box["kind"] == "box" and box["fill"] == "#1a3366" and box["bbox"] == [0.0, 0.0, 150.0, 842.0]


# ---------- shapes ----------

def shapes_of(tmp_path, drawing):
    return read(tmp_path, drawing + block(60, 780, 100))["shapes"]


def test_a_thin_filled_bar_is_a_rule_with_its_thickness(tmp_path):
    (rule,) = shapes_of(tmp_path, "0 0.5 0.5 rg 60 700 200 1.5 re f\n")
    assert (rule["kind"], rule["fill"], rule["stroke"], rule["width"]) == ("rule", "#008080", None, 1.5)
    assert rule["bbox"] == [60.0, 140.5, 260.0, 142.0] and rule["dash"] is None


def test_a_stroked_line_is_a_rule_with_its_stroke_width_and_colour(tmp_path):
    (rule,) = shapes_of(tmp_path, "1 0 0 RG 0.75 w 60 700 m 260 700 l S\n")
    assert (rule["kind"], rule["fill"], rule["stroke"], rule["width"]) == ("rule", None, "#ff0000", 0.75)


def test_a_vertical_line_is_a_rule_too(tmp_path):
    (rule,) = shapes_of(tmp_path, "0 0 0 RG 1 w 200 300 m 200 600 l S\n")
    assert rule["kind"] == "rule" and rule["width"] == 1.0


def test_a_dashed_line_is_a_dash_with_its_pattern(tmp_path):
    (dash,) = shapes_of(tmp_path, "0.5 0.5 0.5 RG 1 w [3 2] 0 d 60 700 m 260 700 l S\n")
    assert dash["kind"] == "dash" and dash["dash"] == [3.0, 2.0] and dash["stroke"] == "#808080"


def test_a_small_filled_circle_is_a_dot(tmp_path):
    k = 0.5523 * 3
    circle = f"1 0 0 rg 100 600 m 100 {600 + k} {103 - k} 603 103 603 c 103 603 {106 - 0} {600 + k} 106 600 c " \
             f"106 {600 - k} {103 + k} 597 103 597 c {103 - k} 597 100 {600 - k} 100 600 c f\n"
    (dot,) = shapes_of(tmp_path, circle)
    assert dot["kind"] == "dot" and dot["fill"] == "#ff0000"


def test_a_filled_rectangle_is_a_box(tmp_path):
    (box,) = shapes_of(tmp_path, "0.9 0.9 0.9 rg 300 500 120 80 re f\n")
    assert box["kind"] == "box" and box["fill"] == "#e6e6e6" and box["rounded"] is False


def test_an_outlined_rectangle_is_a_box_with_a_stroke(tmp_path):
    (box,) = shapes_of(tmp_path, "0 0 1 RG 2 w 300 500 120 80 re S\n")
    assert box["kind"] == "box" and box["fill"] is None and box["stroke"] == "#0000ff" and box["width"] == 2.0


def test_a_rectangle_with_round_corners_is_a_rounded_box(tmp_path):
    r, x, y, w, h = 8, 300, 500, 120, 80
    k = 0.5523 * r
    path = (f"0.8 0.9 1 rg {x + r} {y} m {x + w - r} {y} l {x + w - r + k} {y} {x + w} {y + r - k} {x + w} {y + r} c "
            f"{x + w} {y + h - r} l {x + w} {y + h - r + k} {x + w - r + k} {y + h} {x + w - r} {y + h} c "
            f"{x + r} {y + h} l {x + r - k} {y + h} {x} {y + h - r + k} {x} {y + h - r} c "
            f"{x} {y + r} l {x} {y + r - k} {x + r - k} {y} {x + r} {y} c f\n")
    (box,) = shapes_of(tmp_path, path)
    assert box["kind"] == "box" and box["rounded"] is True


# ---------- columns ----------

def stack(x, top, n, label, size=10, color="0 0 0"):
    return "".join(text("F1", size, x, top - 14 * i, f"{label} {i} some words", color) for i in range(n))


def test_two_stacks_of_lines_are_a_main_column_and_a_side_column(tmp_path):
    columns = read(tmp_path, stack(40, 780, 30, "Side") + stack(200, 780, 40, "The main text goes on and on"))["columns"]
    assert columns["count"] == 2
    side, main = columns["bands"]
    assert (side["kind"], main["kind"]) == ("side", "main") and side["x1"] < 200 <= main["x0"]
    assert side["lines"] == 30 and main["lines"] == 40 and side["background"] is None


def titled(x, kinds):
    """A stack of body lines at *x* with whole-line section titles (the bold one is the font's) above its lines."""
    out = ""
    for i, title in enumerate(kinds):
        out += text("F2", 12, x, 780 - 90 * i, title) + stack(x, 764 - 90 * i, 5, "A line of the body text that runs on and on")
    return out


def equal_kinds(tmp_path, left, right):
    columns = read(tmp_path, titled(40, left) + titled(300, right))["columns"]
    assert columns["count"] == 2
    return [b["kind"] for b in columns["bands"]]


def test_equal_columns_with_more_section_titles_on_the_left_have_it_as_the_side(tmp_path):
    assert equal_kinds(tmp_path, ["Skills", "Education", "Languages"], ["Profile", "Experience"]) == ["side", "main"]


def test_equal_columns_with_more_section_titles_on_the_right_have_it_as_the_side(tmp_path):
    assert equal_kinds(tmp_path, ["Profile", "Experience"], ["Skills", "Education", "Languages"]) == ["main", "side"]


def test_only_side_kind_titles_are_counted_for_the_side_of_equal_columns(tmp_path):
    assert equal_kinds(tmp_path, ["Profile", "Experience", "Projects"], ["Skills"]) == ["main", "side"]
    assert equal_kinds(tmp_path, ["Skills"], ["Profile", "Experience", "Projects"]) == ["side", "main"]


def test_equal_columns_with_no_section_titles_have_the_right_one_as_the_side(tmp_path):
    assert equal_kinds(tmp_path, ["Alpha", "Beta"], ["Gamma", "Delta"]) == ["main", "side"]


def test_equal_columns_with_as_many_section_titles_each_have_the_right_one_as_the_side(tmp_path):
    assert equal_kinds(tmp_path, ["Skills", "Education"], ["Languages", "Interests"]) == ["main", "side"]


def test_one_stack_is_one_column(tmp_path):
    columns = read(tmp_path, stack(60, 780, 40, "The one column of text"))["columns"]
    assert columns["count"] == 1 and columns["bands"][0]["kind"] == "only"


def test_a_banner_over_both_columns_does_not_join_them(tmp_path):
    banner = text("F2", 24, 40, 810, "A Name Over Both Columns Of The Page Here")
    columns = read(tmp_path, banner + stack(40, 770, 30, "Side") + stack(260, 770, 30, "Main text body of words"))["columns"]
    assert columns["count"] == 2


def test_dates_on_the_right_of_a_single_column_are_not_a_column(tmp_path):
    content = ""
    for job in range(8):
        top = 780 - job * 90
        content += text("F2", 11, 50, top, f"Role number {job}, Company") + text("F1", 10, 470, top, "2019 - 2021")
        content += stack(60, top - 14, 4, "Did something useful")
    assert read(tmp_path, content)["columns"]["count"] == 1


def test_a_note_in_the_margin_is_not_a_column(tmp_path):
    columns = read(tmp_path, stack(50, 780, 40, "The one column of text") + text("F1", 8, 500, 400, "a note"))["columns"]
    assert columns["count"] == 1


def test_a_sidebar_on_a_coloured_box_has_its_background(tmp_path):
    drawing = "0.1 0.2 0.4 rg 0 0 170 842 re f\n"
    columns = read(tmp_path, drawing + stack(20, 780, 30, "Side", color="1 1 1") + stack(200, 780, 40, "Main text of the page"))["columns"]
    side, main = columns["bands"]
    assert side["kind"] == "side" and side["background"] == "#1a3366" and main["background"] is None


# ---------- name, headings, colours ----------

NAVY = "0.1 0.2 0.5"


def cv_with_headings(rule=""):
    out = text("F2", 26, 50, 790, "Mira Valdis", NAVY)
    y = 740
    for heading in ("WORK EXPERIENCE", "PROJECTS", "VOLUNTEERING"):
        out += text("F2", 13, 50, y, heading, NAVY)
        if rule:
            out += rule.format(y=y - 4)
        out += "".join(text("F1", 10, 50, y - 20 - 13 * i, f"A line of body text number {i} under it") for i in range(5))
        y -= 120
    return out


def test_the_name_is_the_largest_line_of_the_first_page(tmp_path):
    name = read(tmp_path, cv_with_headings())["name"]
    assert name["text"] == "Mira Valdis" and name["size"] == 26.0 and name["color"] == "#1a3380" and name["family"] == "Helvetica"


def test_headings_share_a_style_larger_than_the_body(tmp_path):
    style = read(tmp_path, cv_with_headings())
    assert [h["text"] for h in style["headings"]] == ["WORK EXPERIENCE", "PROJECTS", "VOLUNTEERING"]
    first = style["headings"][0]
    assert (first["size"], first["color"], first["weight"], first["case"], first["italic"]) == (13.0, "#1a3380", 700, "upper", False)
    assert first["rule"] is None
    assert style["heading_style"] == {"size": 13.0, "color": "#1a3380", "weight": 700, "family": "Helvetica",
                                      "case": "upper", "italic": False, "rule": None}


def test_a_rule_just_under_a_heading_belongs_to_it(tmp_path):
    style = read(tmp_path, cv_with_headings("0.1 0.2 0.5 rg 50 {y} 90 1 re f\n"))
    rule = style["headings"][0]["rule"]
    assert rule["color"] == "#1a3380" and rule["width"] == 1.0 and rule["span"] == "text" and 1 <= rule["gap"] <= 8
    assert rule["x0"] == 50.0 and rule["x1"] == 140.0 and style["heading_style"]["rule"]["span"] == "text"


def test_a_rule_across_the_column_is_a_column_wide_rule(tmp_path):
    style = read(tmp_path, cv_with_headings("0.5 0.5 0.5 RG 0.5 w 50 {y} m 540 {y} l S\n"))
    assert style["headings"][0]["rule"]["span"] == "column"


def test_the_case_of_a_heading_is_upper_title_or_as_written(tmp_path):
    content = text("F2", 26, 50, 790, "Mira Valdis")
    for i, heading in enumerate(["Work Experience", "Core Projects", "Volunteer Work"]):
        content += text("F2", 13, 50, 740 - 80 * i, heading) + text("F1", 10, 50, 720 - 80 * i, "A line of the body text here")
    assert {h["case"] for h in read(tmp_path, content)["headings"]} == {"title"}
    content = text("F2", 26, 50, 790, "Mira Valdis")
    for i, heading in enumerate(["Work experience", "Core projects", "Volunteer work"]):
        content += text("F2", 13, 50, 740 - 80 * i, heading) + text("F1", 10, 50, 720 - 80 * i, "A line of the body text here")
    assert {h["case"] for h in read(tmp_path, content)["headings"]} == {"as_written"}


def test_a_known_section_name_is_a_heading_even_alone_and_in_another_language(tmp_path):
    content = body() + text("F2", 10, 50, 100, "Formation") + text("F1", 10, 50, 86, "A school and a year of study")
    headings = read(tmp_path, content)["headings"]
    assert [h["text"] for h in headings] == ["Formation"]


def test_a_section_name_set_in_the_body_style_is_no_heading(tmp_path):
    assert read(tmp_path, body() + text("F1", 10, 50, 100, "Education"))["headings"] == []


def test_a_bold_section_name_at_the_body_size_is_a_heading(tmp_path):
    assert [h["text"] for h in read(tmp_path, body() + text("F2", 10, 50, 100, "Education"))["headings"]] == ["Education"]


def test_the_text_colour_is_the_one_most_characters_have_and_the_accent_the_strongest_other(tmp_path):
    colors = read(tmp_path, cv_with_headings())["colors"]
    assert colors["text"] == "#000000" and colors["accent"] == "#1a3380"
    assert "palette" not in colors


def test_a_cv_in_black_and_grey_has_no_accent(tmp_path):
    content = body() + text("F1", 10, 50, 100, "Grey words in the foot of the page", "0.4 0.4 0.4")
    assert read(tmp_path, content)["colors"]["accent"] is None


def test_a_coloured_shape_counts_towards_the_accent(tmp_path):
    content = body() + "0.9 0.3 0.1 rg 400 400 150 150 re f\n"
    assert read(tmp_path, content)["colors"]["accent"] == "#e64d1a"


# ---------- photo and images ----------

RED = {"Im1": (2, 2, bytes([255, 0, 0] * 4))}


def image_at(x, y, w, h):
    return f"q {w} 0 0 {h} {x} {y} cm /Im1 Do Q\n"


def test_a_portrait_sized_image_on_the_first_page_is_the_photo(tmp_path):
    style = read(tmp_path, image_at(450, 650, 90, 120) + body(), images=RED)
    assert style["photo"] == {"page": 1, "bbox": [450.0, 72.0, 540.0, 192.0], "shape": "rect"}


def test_an_image_clipped_to_a_circle_is_a_round_photo(tmp_path):
    cx, cy, r = 495, 700, 50
    k = 0.5523 * r
    clip = (f"q {cx - r} {cy} m {cx - r} {cy + k} {cx - k} {cy + r} {cx} {cy + r} c {cx + k} {cy + r} {cx + r} {cy + k} {cx + r} {cy} c "
            f"{cx + r} {cy - k} {cx + k} {cy - r} {cx} {cy - r} c {cx - k} {cy - r} {cx - r} {cy - k} {cx - r} {cy} c W n\n"
            f"{2 * r} 0 0 {2 * r} {cx - r} {cy - r} cm /Im1 Do Q\n")
    assert read(tmp_path, clip + body(), images=RED)["photo"]["shape"] == "circle"


def clipped_image(x, y, w, h, radius):
    """the picture clipped to a box with corners of *radius* (half the side: a circle), top left corner (x, y + h)"""
    r, k = radius, 0.5523 * radius
    x1, y1 = x + w, y + h
    path = (f"{x + r} {y} m {x1 - r} {y} l {x1 - r + k} {y} {x1} {y + r - k} {x1} {y + r} c {x1} {y1 - r} l "
            f"{x1} {y1 - r + k} {x1 - r + k} {y1} {x1 - r} {y1} c {x + r} {y1} l {x + r - k} {y1} {x} {y1 - r + k} {x} {y1 - r} c "
            f"{x} {y + r} l {x} {y + r - k} {x + r - k} {y} {x + r} {y} c h W n\n")
    return f"q {path}{w} 0 0 {h} {x} {y} cm /Im1 Do Q\n"


@pytest.mark.parametrize("side", [48, 64, 86, 100, 140])
def test_a_round_photo_of_any_size_is_a_circle(tmp_path, side):
    style = read(tmp_path, clipped_image(450, 650, side, side, side / 2) + body(), images=RED)
    assert style["photo"]["shape"] == "circle"
    x0, y0, x1, y1 = style["photo"]["bbox"]
    assert abs((x1 - x0) - side) < 2 and abs((y1 - y0) - side) < 2


@pytest.mark.parametrize("side,fraction", [(64, 0), (86, 0.06), (86, 0.15), (100, 0.24), (140, 0.24), (48, 0.15)])
def test_a_square_or_rounded_photo_is_a_rect_whatever_its_corner_radius_up_to_a_quarter(tmp_path, side, fraction):
    style = read(tmp_path, clipped_image(450, 650, side, side, side * fraction) + body(), images=RED)
    assert style["photo"]["shape"] == "rect"


def test_an_oval_photo_is_a_rect_for_the_stylist_has_only_a_circle_to_draw(tmp_path):
    assert read(tmp_path, clipped_image(450, 650, 70, 100, 35) + body(), images=RED)["photo"]["shape"] == "rect"


def test_a_square_picture_with_a_light_backdrop_and_a_dark_oval_is_a_rect_photo(tmp_path):
    # 40 x 40 pixels of white with a dark ellipse 28 wide and 34 tall: what is seen is taller than wide
    rows = []
    for yy in range(40):
        for xx in range(40):
            inside = ((xx - 19.5) / 14) ** 2 + ((yy - 19.5) / 17) ** 2 <= 1
            rows.append((60, 40, 30) if inside else (255, 255, 255))
    data = bytes(c for px in rows for c in px)
    style = read(tmp_path, image_at(440, 650, 100, 100) + body(), images={"Im1": (40, 40, data)})
    assert style["photo"]["shape"] == "rect"


def cover_clipped(x, y, side, radius, drawn_height):
    """a picture drawn *side* wide and *drawn_height* tall, centred, under a clip of *side* x *side* (object-fit: cover)"""
    clip = clipped_image(x, y, side, side, radius)
    return clip.split(f"{side} 0 0 {side}")[0] + f"{side} 0 0 {drawn_height} {x} {y - (drawn_height - side) / 2} cm /Im1 Do Q\n"


@pytest.mark.parametrize("under", ["", "0 0 0 RG 1.5 w 50 712 m 545 712 l S\n", text("F1", 10, 400, 710, "Profile heading words long")])
def test_a_cover_fitted_portrait_under_a_round_clip_is_a_circle_of_the_clip_whatever_is_under_the_overflow(tmp_path, under):
    style = read(tmp_path, cover_clipped(470, 720, 86, 43, 115) + under + body(), images=RED, size=(595, 842))
    assert style["photo"] == {"page": 1, "bbox": [470.0, 36.0, 556.0, 122.0], "shape": "circle"}


def test_a_page_sized_image_is_a_background_not_a_photo(tmp_path):
    style = read(tmp_path, image_at(0, 0, 595, 842) + body(), images=RED)
    assert style["photo"] is None and style["icons"] == []


@pytest.mark.parametrize("w,h", [(20, 20), (300, 40), (60, 200)])
def test_an_image_too_small_or_too_long_is_no_photo(tmp_path, w, h):
    assert read(tmp_path, image_at(400, 600, w, h) + body(), images=RED)["photo"] is None


def test_an_image_on_a_later_page_is_no_photo(tmp_path):
    style = read_pages(tmp_path, [body(), image_at(400, 600, 90, 120) + body()], images=RED)
    assert style["photo"] is None


# ---------- icons ----------

def star(cx, cy, r, color="1 0 0"):
    import math

    pts = [(cx + (r if i % 2 == 0 else r * 0.4) * math.sin(i * math.pi / 5), cy + (r if i % 2 == 0 else r * 0.4) * math.cos(i * math.pi / 5))
           for i in range(10)]
    return f"{color} rg {pts[0][0]:.2f} {pts[0][1]:.2f} m " + " ".join(f"{x:.2f} {y:.2f} l" for x, y in pts[1:]) + " f\n"


def test_a_small_vector_drawing_is_an_icon_next_to_its_text(tmp_path):
    style = read(tmp_path, star(60, 703, 5) + text("F1", 10, 70, 700, "name@example.com") + body())
    (icon,) = style["icons"]
    assert icon["source"] == "vector" and icon["page"] == 1 and icon["color"] == "#ff0000" and icon["fill_rule"] == "evenodd"
    assert icon["near"] == {"text": "name@example.com", "side": "right"}
    assert icon["d"].startswith("M") and 8 <= float(icon["viewBox"].split()[2]) <= 11
    # the drawing's box in page points, from the top left: about 10 wide around x 60, near y 139
    x0, y0, x1, y1 = icon["bbox"]
    assert 54 <= x0 <= 56 and 64 <= x1 <= 66 and 134 <= y0 <= 139 and 140 <= y1 <= 150


def test_a_lone_icon_after_the_text_has_it_on_its_left(tmp_path):
    style = read(tmp_path, text("F1", 10, 300, 700, "Phone") + star(335, 703, 5) + body())
    assert style["icons"][0]["near"]["side"] == "left" and style["icons"][0]["near"]["text"] == "Phone"


def test_rules_dots_and_boxes_are_no_icons(tmp_path):
    drawing = "0 0 0 rg 60 700 200 1 re f\n0.9 0.9 0.9 rg 300 500 40 30 re f\n"
    assert read(tmp_path, drawing + body())["icons"] == []


def test_drawings_that_touch_are_one_icon(tmp_path):
    # a house: a roof and a wall painted as two paths that share an edge
    roof = "0 0 1 rg 50 700 m 55 705 l 60 710 l 65 705 l 70 700 l f\n"
    wall = "0 0 1 rg 52 691 m 68 691 l 68 700 l 60 702 l 52 700 l f\n"
    assert len(read(tmp_path, roof + wall + body())["icons"]) == 1


def test_a_large_drawing_is_not_an_icon(tmp_path):
    assert read(tmp_path, star(300, 400, 60) + body())["icons"] == []


def test_a_run_in_an_icon_font_is_an_icon_run_left_out_of_the_layout(tmp_path):
    content = text("FA", 10, 400, 700, "A") + text("F1", 10, 420, 700, "name@example.com") + body()
    style = read(tmp_path, content, fonts={"FA": "FontAwesome"})
    run = run_of(style, "A")
    assert run["icon"] is True and run_of(style, "name@")["icon"] is False
    assert {f["family"] for f in style["fonts"]} >= {"FontAwesome"}


def test_a_small_picture_that_is_no_photo_is_an_icon(tmp_path):
    style = read(tmp_path, image_at(400, 700, 16, 16) + text("F1", 10, 420, 704, "Copenhagen") + body(), images=RED)
    (icon,) = style["icons"]
    assert icon["source"] == "image" and icon["near"]["text"] == "Copenhagen" and icon["color"] == "#ff0000"


def test_a_bullet_in_a_symbol_font_is_no_icon(tmp_path):
    content = text("SY", 10, 50, 700, "\xb7") + text("F1", 10, 62, 700, "First point of the list") + body()
    style = read(tmp_path, content, fonts={"SY": "Symbol"})
    assert style["icons"] == []


# ---------- what the corpus showed ----------

def test_columns_ten_points_apart_under_a_full_width_header_are_two_columns(tmp_path):
    header = "".join(text("F1", 10, 40, 800 - 14 * i, "A header line that runs across the whole width of the page, " * 2) for i in range(8))
    columns = read(tmp_path, header + stack(40, 650, 30, "Left column words here") + stack(300, 650, 24, "Right col text"))["columns"]
    assert columns["count"] == 2 and [b["kind"] for b in columns["bands"]] == ["main", "side"]


def test_a_bullet_set_apart_from_its_text_does_not_split_a_column(tmp_path):
    content = "".join(text("F1", 10, 50, 780 - 14 * i, "\x95") + text("F1", 10, 62, 780 - 14 * i, f"A bullet point with a line of text {i}")
                      for i in range(30))
    assert read(tmp_path, content)["columns"]["count"] == 1


def small_caps(x, y, first, rest, color="0 0 0"):
    """a heading in small capitals: the first letter large, the rest small (two runs, two sizes)"""
    return text("F1", 12, x, y, first, color) + text("F1", 9.6, x + 8.5, y, rest, color)


def test_a_small_caps_line_is_one_heading_and_the_name_is_the_whole_line(tmp_path):
    content = text("F1", 24, 50, 790, "J") + text("F1", 19, 66, 790, "ONAS") + text("F1", 24, 120, 790, "B") + text("F1", 19, 136, 790, "REKKE")
    for i, (a, b) in enumerate([("E", "XPERIENCE"), ("P", "ROJECTS"), ("V", "OLUNTEERING")]):
        content += small_caps(50, 700 - 90 * i, a, b) + stack(50, 680 - 90 * i, 4, "A line of the body text")
    style = read(tmp_path, content)
    assert style["name"]["size"] == 24.0 and style["name"]["text"].replace(" ", "") == "JONASBREKKE"
    assert [h["text"].replace(" ", "") for h in style["headings"]] == ["EXPERIENCE", "PROJECTS", "VOLUNTEERING"]
    assert style["headings"][0]["size"] == 12.0


def test_a_picture_with_a_blank_margin_is_a_rect_photo_the_size_of_what_is_seen(tmp_path):
    # 4 x 4 pixels, the middle 2 x 2 red: drawn 120 pt wide, so the picture seen is the middle 60 pt
    rows = [[(255, 255, 255)] * 4, [(255, 255, 255), (255, 0, 0), (255, 0, 0), (255, 255, 255)],
            [(255, 255, 255), (255, 0, 0), (255, 0, 0), (255, 255, 255)], [(255, 255, 255)] * 4]
    data = bytes(c for row in rows for px in row for c in px)
    style = read(tmp_path, image_at(430, 650, 120, 120) + body(), images={"Im1": (4, 4, data)})
    assert style["photo"]["shape"] == "rect"
    x0, y0, x1, y1 = style["photo"]["bbox"]
    assert 458 <= x0 <= 462 and 518 <= x1 <= 522 and abs((y1 - y0) - 60) < 4


def test_letter_spaced_capitals_are_read_as_the_word(tmp_path):
    # every letter its own object with a gap that is sometimes over a fifth of the size (a Courier glyph is 6 pt wide)
    content, x = "", 50.0
    for letter, step in zip("EXPERIENCE", [7.0, 8.4, 7.0, 8.4, 7.0, 8.4, 7.0, 8.4, 7.0, 0]):
        content += text("F4", 11, x, 700, letter)
        x += step
    assert run_of(read(tmp_path, content + body()), "E")["text"] == "EXPERIENCE"


def test_a_sentence_of_short_words_keeps_its_spaces(tmp_path):
    assert run_of(read(tmp_path, text("F1", 10, 50, 700, "I AM IN IT") + body()), "AM")["text"] == "I AM IN IT"


# ---------- review: serif, nameless fonts, icon fonts, italic ----------

@pytest.mark.parametrize("name,flags,serif", [
    ("TeXGyreHeros-Regular", 0x6, False),   # pdfTeX sets the serif bit on a sans font
    ("Figtree-Regular", 0x4, False),        # Chromium sets only the symbolic bit
    ("NimbusSanL-Regu", 0x22, False), ("Lato-Bold", 0x22, False), ("Optima-Bold", 0x20, False),
    ("URW Palladio L", 0x22, True), ("LMRoman10-Regular", 0x22, True), ("Times-Roman", 0x0, True),
    ("Mystery-Regular", 0x22, True),        # the name says nothing: the flag decides
    ("Mystery-Regular", 0x20, False),
])
def test_a_sans_or_serif_name_decides_before_the_flag(name, flags, serif):
    assert style_extract.is_serif(name, flags) is serif


def test_the_force_bold_flag_makes_a_font_bold_and_an_italic_angle_italic():
    facts = style_extract.font_facts("Mystery-Regular", flags=0x40000, italic_angle=-12, family="")
    assert facts["weight"] == 700 and facts["italic"] is True
    assert style_extract.font_facts("Mystery-Regular", flags=0, italic_angle=0, family="")["weight"] == 400


def test_a_nameless_run_takes_the_font_of_the_named_space_on_its_line():
    named = {"font": "YoungSerif-Regular", "family": "Young Serif", "weight": 400, "italic": False, "serif": True, "fixed": False}
    nameless = {"page": 1, "baseline": 100.0, "size": 24.0, "font": "", "family": "", "weight": 400, "italic": False,
                "serif": False, "fixed": False, "type3": False}
    far = {**nameless, "baseline": 300.0}
    anchors = [{"page": 1, "baseline": 100.4, "size": 24.0, "x": 72.0, **named}]
    style_extract.name_nameless([nameless, far], anchors)
    assert nameless["font"] == "YoungSerif-Regular" and nameless["family"] == "Young Serif" and nameless["serif"] is True
    assert nameless["type3"] is False
    assert far["font"] == "" and far["type3"] is True  # nothing named on its line: marked, not guessed


def test_fonts_say_whether_all_their_runs_are_icons(tmp_path):
    content = text("FA", 10, 400, 700, "A") + text("F1", 10, 420, 700, "name@example.com") + body()
    fonts = {f["family"]: f for f in read(tmp_path, content, fonts={"FA": "FontAwesome"})["fonts"]}
    assert fonts["FontAwesome"]["icon"] is True and fonts["Helvetica"]["icon"] is False
    assert fonts["Helvetica"]["type3"] is False


def run(font, text_, **kw):
    return {"font": font, "text": text_, "icon": False, **kw}


def test_private_use_control_and_dingbat_characters_mark_an_icon_run_in_any_font():
    runs = [run("Neutral-Regular", ""), run("Neutral-Regular", "\x01"), run("Neutral-Regular", "✓"),
            run("Neutral-Regular", "Plain words")]
    style_extract.style_icons.mark_icon_runs(runs)
    assert [r["icon"] for r in runs] == [True, True, True, False]


@pytest.mark.parametrize("name", ["FontAwesome", "fontello", "Material Icons", "Symbol", "Wingdings", "Webdings",
                                  "ZapfDingbats", "Zapf Dingbats", "MT Extra", "MTExtra", "Marlett"])
def test_icon_font_names_the_icon_and_symbol_fonts(name):
    assert style_extract.style_icons.icon_font(name)


@pytest.mark.parametrize("name", ["Calibri", "Lato-Regular", "CMR10", "Times New Roman"])
def test_icon_font_leaves_a_text_font_alone(name):
    assert not style_extract.style_icons.icon_font(name)


def test_glyph_only_is_private_use_control_or_dingbats():
    assert style_extract.style_icons.glyph_only("\uf095\u2706")
    assert not style_extract.style_icons.glyph_only("\uf095 Phone")


def test_a_font_whose_runs_are_all_a_symbol_or_two_is_an_icon_font():
    runs = [run("Odd-Regular", "@"), run("Odd-Regular", "→"), run("Body-Regular", "Words"), run("Body-Regular", "A")]
    style_extract.style_icons.mark_icon_runs(runs)
    assert [r["icon"] for r in runs] == [True, True, False, False]


def test_a_bullet_and_a_letter_or_digit_are_not_icons_whatever_their_font():
    runs = [run("Symbol", "•"), run("Odd-Regular", "1"), run("Odd-Regular", "1")]
    style_extract.style_icons.mark_icon_runs(runs)
    assert [r["icon"] for r in runs] == [False, False, False]


def test_level_dots_and_bullets_drawn_with_an_icon_font_are_no_icons():
    # the draft keeps them (`●●●○○` is 3 of 5, #313); the icon font's other glyphs read back as stray characters
    runs = [run("FontAwesome", "○ ○ ○"), run("FontAwesome", "○"), run("FontAwesome", "½"), run("FontAwesome", "\x11"),
            run("Body-Regular", "Words"), run("Body-Regular", "•")]
    style_extract.style_icons.mark_icon_runs(runs)
    assert [r["icon"] for r in runs] == [False, False, True, True, False, False]


def dots(text_, color, x0, x1, y=100):
    return run("FontAwesome", text_, color=color, page=1, size=8, bbox=[x0, y, x1, y + 8])


STYLE = {"colors": {"text": "#444444", "accent": "#3a1800"}, "page": {"background": None}, "columns": {"bands": []}}


def test_level_rows_fill_the_accent_or_text_colour_and_leave_other_rows():
    rows = style_extract.style_icons.level_rows([dots("○ ○ ○", "#3a1800", 0, 20), dots("○ ○", "#c7c7c7", 22, 36)], STYLE)
    assert rows == [(1, [0, 100, 36, 108], "●●●○○")]


def test_a_row_of_the_filled_colour_is_all_filled_once_the_cv_has_a_two_colour_row():
    runs = [dots("○ ○ ○", "#3a1800", 0, 20), dots("○ ○", "#c7c7c7", 22, 36), dots("○ ○ ○", "#3a1800", 0, 20, y=120),
            dots("○ ○", "#c7c7c7", 0, 14, y=140)]
    rows = style_extract.style_icons.level_rows(runs, STYLE)
    assert (1, [0, 120, 20, 128], "●●●") in rows and len(rows) == 2
    assert style_extract.style_icons.level_rows(runs[2:3], STYLE) == []


def test_on_a_dark_band_the_lighter_dots_are_filled_when_neither_colour_is_the_cvs():
    style = {**STYLE, "colors": {"text": "#ff0000", "accent": None},
             "columns": {"bands": [{"x0": 0, "x1": 50, "background": "#222222"}]}}
    rows = style_extract.style_icons.level_rows([dots("○ ○", "#ffffff", 0, 14), dots("○", "#555555", 16, 24)], style)
    assert rows[0][2] == "●●○"


def test_a_gap_wider_than_the_font_or_another_line_splits_a_row_and_three_colours_are_no_level():
    level_rows = style_extract.style_icons.level_rows
    assert level_rows([dots("○", "#3a1800", 0, 8), dots("○", "#c7c7c7", 40, 48)], STYLE) == []
    assert level_rows([dots("○", "#3a1800", 0, 8), dots("○", "#c7c7c7", 9, 17, y=103)], STYLE) == []
    assert level_rows([dots("○", "#3a1800", 0, 8), dots("○", "#c7c7c7", 9, 17), dots("○", "#888888", 18, 26)], STYLE) == []


def test_a_small_photo_with_a_blank_border_is_not_also_an_icon(tmp_path):
    rows = [[(255, 255, 255)] * 4] + [[(255, 255, 255), (255, 0, 0), (255, 0, 0), (255, 255, 255)]] * 2 + [[(255, 255, 255)] * 4]
    data = bytes(c for row in rows for px in row for c in px)
    style = read(tmp_path, image_at(450, 650, 44, 44) + body(), images={"Im1": (4, 4, data)})
    assert style["photo"] is not None and style["icons"] == []


def italic_headings(font):
    content = text("F2", 26, 50, 790, "Mira Valdis")
    for i, heading in enumerate(["WORK EXPERIENCE", "PROJECTS", "VOLUNTEERING"]):
        content += text(font, 13, 50, 740 - 90 * i, heading) + stack(50, 720 - 90 * i, 4, "A line of the body text")
    return content


def test_headings_and_their_style_say_when_they_are_italic(tmp_path):
    style = read(tmp_path, italic_headings("F5"))
    assert all(h["italic"] is True for h in style["headings"]) and style["heading_style"]["italic"] is True


# ---------- review: branches the corpus does not reach ----------

def test_a_circle_bigger_than_a_dot_is_a_rounded_box(tmp_path):
    k = 0.5523 * 15
    cx, cy = 300, 500
    circle = (f"0.8 0.8 0.9 rg {cx - 15} {cy} m {cx - 15} {cy + k} {cx - k} {cy + 15} {cx} {cy + 15} c "
              f"{cx + k} {cy + 15} {cx + 15} {cy + k} {cx + 15} {cy} c {cx + 15} {cy - k} {cx + k} {cy - 15} {cx} {cy - 15} c "
              f"{cx - k} {cy - 15} {cx - 15} {cy - k} {cx - 15} {cy} c f\n")
    (box,) = read(tmp_path, circle + body())["shapes"]
    assert box["kind"] == "box" and box["rounded"] is True


def test_a_path_that_paints_nothing_is_no_shape(tmp_path):
    clip = "100 500 m 300 500 l 300 600 l 100 600 l W n\n"  # a clip: no fill, no stroke
    assert read(tmp_path, clip + body())["shapes"] == []


def test_text_that_is_not_stacked_anywhere_is_still_one_only_column(tmp_path):
    scattered = "".join(text("F1", 10, 60 + 50 * i, 700 - 150 * i, "One long line of the CV that stands on its own " * 2) for i in range(4))
    columns = read(tmp_path, scattered)["columns"]
    assert columns["count"] == 1 and columns["bands"][0]["kind"] == "only"


def test_a_page_of_lines_in_two_styles_has_no_name(tmp_path):
    # every line is half bold, half regular: no line is one style, so nothing is read as a name
    content = "".join(text("F2", 12, 50, 780 - 14 * i, "Lab") + text("F1", 12, 73, 780 - 14 * i, f"el {i} has a value that follows")
                      for i in range(8))
    assert read(tmp_path, content)["name"] is None


def test_a_picture_the_colour_of_what_is_around_it_keeps_its_box(tmp_path):
    white = {"Im1": (2, 2, bytes([255, 255, 255] * 4))}
    style = read(tmp_path, image_at(450, 650, 90, 120) + body(), images=white)
    assert style["photo"]["bbox"] == [450.0, 72.0, 540.0, 192.0] and style["photo"]["shape"] == "rect"


def test_a_page_with_only_a_page_number_adds_no_margins(tmp_path):
    margins = read_pages(tmp_path, [block(60, 780, 100), text("F1", 9, 290, 20, "2")])["page"]["margins"]
    assert 59 <= margins["left"] <= 62


def test_text_that_is_all_rotated_has_no_columns(tmp_path):
    side = "".join(f"BT /F1 10 Tf 0 1 -1 0 {300 + 14 * i} 200 Tm (A rotated line of text number {i} of the page) Tj ET\n" for i in range(5))
    style = read(tmp_path, side)
    assert style["columns"] == {"count": 0, "bands": []}


def test_a_drawing_that_shows_nothing_on_the_page_is_no_icon(tmp_path):
    assert read(tmp_path, star(60, 703, 5, color="1 1 1") + body())["icons"] == []


def test_an_icon_font_used_once_for_a_bullet_stays_an_icon_font():
    runs = [{"font": "FontAwesome", "family": "FontAwesome", "weight": 400, "italic": False, "serif": False,
             "fixed": False, "embedded": True, "type3": False, "text": t, "icon": icon}
            for t, icon in (("[", True), ("Ó", True), ("○", False))]
    assert style_extract._fonts_used(runs)[0]["icon"] is True


def font_run(font, text_, icon):
    return {"font": font, "family": font, "weight": 400, "italic": False, "serif": False, "fixed": False,
            "embedded": True, "type3": False, "text": text_, "icon": icon}


@pytest.mark.parametrize("seps", [["|", "/", ",", ";"], ["·", "–", "/", "•", ","], ["|", "—", ".", ":"]])
def test_a_font_of_separators_only_is_no_icon_font(seps):
    runs = [run("Sep-Regular", t) for t in seps]
    style_extract.style_icons.mark_icon_runs(runs)
    assert [r["icon"] for r in runs] == [False] * len(seps)
    assert all(not f["icon"] for f in style_extract._fonts_used([font_run("Sep-Regular", t, r["icon"])
                                                                 for t, r in zip(seps, runs)]))


def test_a_font_of_separators_and_one_real_icon_marks_only_the_icon():
    runs = [run("Odd-Regular", "@"), run("Odd-Regular", "|"), run("Odd-Regular", "/")]
    style_extract.style_icons.mark_icon_runs(runs)
    assert [r["icon"] for r in runs] == [True, False, False]


def test_icon_fonts_stay_icons_beside_the_separator_rule():
    runs = [run("FontAwesome", "A"), run("FontAwesome", "b"), run("Neutral-Regular", "\uf095"), run("Wingdings", "(")]
    style_extract.style_icons.mark_icon_runs(runs)
    assert all(r["icon"] for r in runs)


def test_a_font_of_bullets_only_is_no_icon_font():
    assert style_extract._fonts_used([font_run("Dots", "·", False)])[0]["icon"] is False


def test_separator_runs_are_no_icons_and_stay_in_the_text(tmp_path):
    content = (text("F1", 10, 50, 740, "Python") + text("F6", 10, 110, 740, "|") + text("F1", 10, 125, 740, "Rust")
               + text("F6", 10, 160, 740, "/") + text("F1", 10, 175, 740, "Go") + body())
    style = read(tmp_path, content, fonts={"F6": "SomeFont"})
    assert style["icons"] == []
    seps = [r for r in style["runs"] if r["text"] in ("|", "/")]
    assert seps and not any(r["icon"] for r in seps)
    assert not any(f["icon"] for f in style["fonts"])


def test_a_font_entry_has_exactly_its_known_keys():
    [entry] = style_extract._fonts_used([font_run("Body", "Words", False)])
    assert set(entry) == {"font", "family", "weight", "italic", "serif", "fixed", "embedded", "type3", "icon",
                          "runs", "chars"}


def test_a_long_separator_run_does_not_unmark_an_icon_in_its_font():
    runs = [run("Odd-Regular", "@"), run("Odd-Regular", " | "), run("Odd-Regular", " / ")]
    style_extract.style_icons.mark_icon_runs(runs)
    assert [r["icon"] for r in runs] == [True, False, False]


def test_a_font_with_an_icon_and_a_separator_is_an_icon_font_and_a_separator_font_is_not():
    fonts = style_extract._fonts_used([font_run("Odd", "@", True), font_run("Odd", "|", False),
                                       font_run("Sep", "|", False), font_run("Sep", "/", False)])
    assert {f["font"]: f["icon"] for f in fonts} == {"Odd": True, "Sep": False}


def test_a_separator_beside_an_icon_in_one_font_is_text_to_every_reader(tmp_path):
    content = (text("F6", 10, 50, 740, "@") + text("F1", 10, 62, 740, "Python") + text("F6", 10, 110, 740, "|")
               + text("F1", 10, 125, 740, "Rust") + body())
    style = read(tmp_path, content, fonts={"F6": "SomeFont"})
    bar = run_of(style, "|")
    assert not bar["icon"] and run_of(style, "@")["icon"]
    boxes = [box for _, box, _ in style_extract.style_icons.draft_edits(style["runs"], style)]
    assert boxes == [run_of(style, "@")["bbox"]]
    assert "|" in style_build.original_text(style, tmp_path / "cv.pdf")
    assert any("|" in r["text"] for r in style_compare._texts(style))
    assert not any("@" in r["text"] for r in style_compare._texts(style))


def test_the_original_text_keeps_the_separators_of_a_separator_font(tmp_path):
    content = (text("F1", 10, 50, 740, "Python") + text("F6", 10, 110, 740, "|") + text("F1", 10, 125, 740, "Rust")
               + body())
    style = read(tmp_path, content, fonts={"F6": "SomeFont"})
    assert "|" in style_build.original_text(style, tmp_path / "cv.pdf")
    assert any(r["text"] == "|" for r in style_compare._texts(style))


def test_spaced_level_dots_do_not_widen_a_column_band():
    # '○ ○ ○ ○' in the icon font is no icon (#315) but is still no column text: the side band ends at its words
    from tests.paths import TESTS_DIR

    style = rules_extract(TESTS_DIR / "tailoring" / "fixtures" / "styles" / "scrubbed-altacv-icons-fr.pdf")
    side = next(b for b in style["columns"]["bands"] if b["kind"] == "side")
    assert side["x1"] == 541.9


# ---------- layouts the template model cannot place (#318) ----------

def three_columns(tmp_path):
    return read(tmp_path, titled(40, ["Skills", "Languages"]) + titled(300, ["Experience"]) + titled(560, ["Education"]),
                size=(900, 800))


def test_three_columns_have_no_place_in_the_template_model(tmp_path):
    style = three_columns(tmp_path)
    assert style["verdict"]["copyable"] is False and style["verdict"]["reason"] == "layout"
    assert style["verdict"]["detail"] == "has three or more columns, which the template model cannot place."
    assert style["columns"]["count"] == 3


def test_a_three_column_cv_keeps_its_text_and_colours_for_the_draft(tmp_path):
    style = three_columns(tmp_path)
    assert len(style["runs"]) > 20 and style["colors"] and style["headings"] and style["fonts"]
