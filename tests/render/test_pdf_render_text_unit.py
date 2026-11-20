"""What `pdf_render.page_texts` hands on of a page's text: words and lines, not pdfium's markers."""

from door.render import pdf_render


def test_a_hyphen_pdfium_marks_at_a_line_break_joins_the_word():
    # pdfium reports a soft hyphen as U+FFFE (a French CV: "appli-quées" broken over two lines)
    assert pdf_render.clean_text("Mathématiques appli￾quées") == "Mathématiques appliquées"
    assert pdf_render.clean_text("appli￾\nquées") == "appliquées"


def test_control_characters_of_icon_glyphs_go_and_lines_stay():
    # a calendar icon came out as U+0011 before every date
    assert pdf_render.clean_text("Michelin\n\x11 Sept. 2024\tParis\x0c") == "Michelin\n Sept. 2024\tParis"
