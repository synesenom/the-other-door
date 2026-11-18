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


def _box(pdf, page, first, last):
    """The box (points from the top left) over characters *first* to *last* of the page's printed ones."""
    _, height, boxes = pdf_render.page_boxes(pdf)[page]
    part = boxes[first:last + 1]
    return [min(b[0] for b in part), height - max(b[3] for b in part), max(b[2] for b in part), height - min(b[1] for b in part)]


def test_a_box_is_rewritten_where_its_first_character_stood_with_a_left_out_box_and_other_pages_and_boxes(tmp_path):
    from tests.pdf_utils import make_pdf

    pdf = make_pdf(tmp_path / "a.pdf", ["AAAA BBBB CCCC", "XXXX YYYY"])
    # printed characters (no spaces): AAAA = 0-3, BBBB = 4-7, CCCC = 8-11
    one = pdf_render.page_texts(pdf, rewrite=[(1, _box(pdf, 0, 8, 11), ""), (1, _box(pdf, 0, 0, 3), "1")])
    assert one[0].split() == ["1", "BBBB"] and one[1].split() == ["XXXX", "YYYY"]
    two = pdf_render.page_texts(pdf, rewrite=[(1, _box(pdf, 0, 0, 3), "1"), (1, _box(pdf, 0, 8, 11), "3")])
    assert two[0].split() == ["1", "BBBB", "3"]
    later = pdf_render.page_texts(pdf, rewrite=[(2, _box(pdf, 1, 4, 7), "Y")])
    assert later[0].split() == ["AAAA", "BBBB", "CCCC"] and later[1].split() == ["XXXX", "Y"]
