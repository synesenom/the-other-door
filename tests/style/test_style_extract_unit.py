"""door.style.style_extract: a CV PDF's style read as facts, on PDFs written by hand (#148)."""

import pytest

from pdf_utils import raw_pdf

from door.style import style_build, style_compare, style_extract


def read(tmp_path, content, **kwargs):
    path = tmp_path / "cv.pdf"
    path.write_bytes(raw_pdf(content, **kwargs))
    return style_extract.extract(path)


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
    return style_extract.extract(path)


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

# ---------- name, headings, colours ----------

NAVY = "0.1 0.2 0.5"


def cv_with_headings():
    out = text("F2", 26, 50, 790, "Mira Valdis", NAVY)
    y = 740
    for heading in ("WORK EXPERIENCE", "PROJECTS", "VOLUNTEERING"):
        out += text("F2", 13, 50, y, heading, NAVY)
        out += "".join(text("F1", 10, 50, y - 20 - 13 * i, f"A line of body text number {i} under it") for i in range(5))
        y -= 120
    return out


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


def test_glyph_only_is_pictographs_and_private_use_with_the_pieces_of_an_emoji_sequence():
    glyph = style_extract.style_icons.glyph_only
    icons = ["\uf095\u2706", "\u260e", "\u2709", "\u2706", "\U0001f4de", "\u260e\ufe0f", "\u2709\ufe0f",
             "\U0001f468\u200d\U0001f4bb", "\U0001f44d\U0001f3fd", "\uf095 \uf096", "\uf095  "]
    text_ = ["\uf095 Phone", "", "  ", "&+\u00bb\u203a\u2192@$\u20ac\u00a9\u2122\u2116\u00d7=", "\u2502", "\u25b8", "\u25c6",
             "\u25ba", "\u25b2", "\u2302", "\u2605\u2605\u2605\u2605\u2606", "\ufe0f"]
    assert all(glyph(t) for t in icons)
    assert not any(glyph(t) for t in text_)


@pytest.mark.parametrize("mark", ["&", "+", "\u00bb", "@"])
def test_an_in_line_mark_in_its_own_display_font_is_text_not_an_icon(mark, tmp_path):
    content = (text("F1", 10, 50, 740, "Cheese") + text("F6", 10, 100, 740, mark) + text("F1", 10, 115, 740, "Wine")
               + body())
    style = read(tmp_path, content, fonts={"F6": "Display-Bold"})
    assert style["icons"] == []
    kept = run_of(style, mark)
    assert not kept["icon"]
    assert not any(f["icon"] for f in style["fonts"])
    assert style_extract.style_icons.draft_edits(style["runs"], style) == []
    assert mark in style_build.original_text(style, tmp_path / "cv.pdf")
    assert any(r["text"] == mark for r in style_compare._texts(style))


@pytest.mark.parametrize("font", ["FontAwesome5Free-Solid", "MaterialIcons-Regular", "Wingdings", "Symbol"])
def test_every_glyph_of_a_font_named_like_an_icon_font_is_an_icon(font):
    runs = [run(font, glyph) for glyph in ["A", "b", "\u2192", "@", "("]]
    style_extract.style_icons.mark_icon_runs(runs)
    assert all(r["icon"] for r in runs)



def test_private_use_and_pictographs_are_icons_in_a_text_font_and_an_arrow_in_a_text_font_is_text():
    runs = [run("Body-Regular", "\uf095"), run("Body-Regular", "\u260e"), run("Body-Regular", "\u2192"),
            run("Body-Regular", "&")]
    style_extract.style_icons.mark_icon_runs(runs)
    assert [r["icon"] for r in runs] == [True, True, False, False]


def test_box_drawing_geometric_bullets_and_rating_stars_in_a_text_or_display_font_are_text():
    runs = [run(f, t) for f in ("Body-Regular", "Display-Bold") for t in ("\u2502", "\u25b8", "\u25c6", "\u25ba", "\u2605\u2605\u2605\u2605\u2606")]
    runs += [run("Body-Regular", t) for t in ("\u260e", "\u2709", "\u2706", "\U0001f600", "\uf095", "\u260e\ufe0f")]
    style_extract.style_icons.mark_icon_runs(runs)
    assert [r["icon"] for r in runs] == [False] * 10 + [True] * 6


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


def test_a_picture_the_colour_of_what_is_around_it_keeps_its_box(tmp_path):
    white = {"Im1": (2, 2, bytes([255, 255, 255] * 4))}
    style = read(tmp_path, image_at(450, 650, 90, 120) + body(), images=white)
    assert style["photo"]["bbox"] == [450.0, 72.0, 540.0, 192.0] and style["photo"]["shape"] == "rect"


def test_a_page_with_only_a_page_number_adds_no_margins(tmp_path):
    margins = read_pages(tmp_path, [block(60, 780, 100), text("F1", 9, 290, 20, "2")])["page"]["margins"]
    assert 59 <= margins["left"] <= 62


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
    runs = [run("Odd-Regular", "\uf095"), run("Odd-Regular", "|"), run("Odd-Regular", "/")]
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


def test_a_font_with_text_marks_in_it_is_no_icon_font_but_one_of_icons_and_bullets_is():
    fonts = style_extract._fonts_used([font_run("Odd", "\uf095", True), font_run("Odd", "|", False),
                                       font_run("Sep", "|", False), font_run("Sep", "/", False),
                                       font_run("Dots", "\uf095", True), font_run("Dots", "•", False)])
    assert {f["font"]: f["icon"] for f in fonts} == {"Odd": False, "Sep": False, "Dots": True}


def test_the_original_text_keeps_the_separators_of_a_separator_font(tmp_path):
    content = (text("F1", 10, 50, 740, "Python") + text("F6", 10, 110, 740, "|") + text("F1", 10, 125, 740, "Rust")
               + body())
    style = read(tmp_path, content, fonts={"F6": "SomeFont"})
    assert "|" in style_build.original_text(style, tmp_path / "cv.pdf")
    assert any(r["text"] == "|" for r in style_compare._texts(style))


# ---------- layouts the template model cannot place (#318) ----------


def test_a_text_font_that_draws_one_pictograph_keeps_its_bullets_as_text():
    runs = [run("Calibri", "☎"), run("Calibri", "+45 12 34 56 78"), run("Calibri", "•"), run("Calibri", "Python")]
    style_extract.style_icons.mark_icon_runs(runs)
    fonts = style_extract.style_icons.icon_fonts(runs)
    assert fonts == set() and not style_extract.style_icons.is_glyph(runs[2], fonts)
    assert style_extract.style_icons.is_glyph(runs[0], fonts)


def test_a_level_dot_drawn_with_an_icon_font_is_a_glyph():
    runs = [run("FontAwesome", ""), run("FontAwesome", "●")]
    style_extract.style_icons.mark_icon_runs(runs)
    fonts = style_extract.style_icons.icon_fonts(runs)
    assert fonts == {"FontAwesome"} and style_extract.style_icons.is_glyph(runs[1], fonts)
