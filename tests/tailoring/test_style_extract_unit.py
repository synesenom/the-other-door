"""door.tailoring.style_extract: a CV PDF's style read as facts, on PDFs written by hand (#148)."""

import pytest

from pdf_utils import raw_pdf

from door.tailoring import style_extract


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
    content = "BT /F1 12 Tf 3 Tr 50 700 Td (ocr layer) Tj ET\n" + body()
    assert not [r for r in read(tmp_path, content)["runs"] if "ocr" in r["text"]]


def test_the_producer_and_creator_are_reported(tmp_path):
    style = read(tmp_path, body(), producer="Test Maker")
    assert style["producer"] == "Test Maker" and style["creator"] == ""
    assert style["version"] == 1
