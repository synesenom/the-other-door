"""What `pdf_render.page_texts` hands on of a page's text: words and lines, not pdfium's markers."""

from door.render import pdf_render


def test_a_hyphen_pdfium_marks_at_a_line_break_joins_the_word():
    # pdfium reports a soft hyphen as U+FFFE (a French CV: "appli-quées" broken over two lines)
    assert pdf_render.clean_text("Mathématiques appli￾quées") == "Mathématiques appliquées"
    assert pdf_render.clean_text("appli￾\nquées") == "appliquées"


def test_control_characters_of_icon_glyphs_go_and_lines_stay():
    # a calendar icon came out as U+0011 before every date
    assert pdf_render.clean_text("Michelin\n\x11 Sept. 2024\tParis\x0c") == "Michelin\n Sept. 2024\tParis"


def test_page_boxes_give_size_and_the_box_of_each_printed_character(tmp_path):
    from door.render import pdf_render
    from tests.pdf_utils import make_pdf

    pdf = make_pdf(tmp_path / "a.pdf", ["Hi there", ""])
    pages = pdf_render.page_boxes(pdf)
    assert len(pages) == 2
    width, height, boxes = pages[0]
    assert (round(width), round(height)) == (595, 842)
    assert len(boxes) == len("Hithere")  # spaces are not ink
    left, bottom, right, top = boxes[0]
    assert 72 <= left < 75 and left < right and bottom < top < height
    assert pages[1][2] == []
