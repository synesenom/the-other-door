"""scripts/style_corpus/scrub_pdf.py and scrub_check.py: the pure parts of the tools that scrub a real CV PDF for the style corpus."""

import importlib.util
import re

import pytest

from paths import REPO_ROOT

# scrub_pdf.py's pure parts (pikepdf, which only its own venv has, is imported where a PDF is opened)
_scrub_spec = importlib.util.spec_from_file_location("scrub_pdf", REPO_ROOT / "scripts" / "style_corpus" / "scrub_pdf.py")
scrub = importlib.util.module_from_spec(_scrub_spec)
_scrub_spec.loader.exec_module(scrub)


def test_a_mac_roman_or_win_ansi_font_names_its_accented_letters_and_its_space():
    mac = scrub.encoding_names("/MacRomanEncoding")
    assert mac[0x8E] == "eacute" and mac[0x87] == "aacute" and mac[65] == "A" and mac[32] == "space"
    assert scrub.encoding_names("/WinAnsiEncoding")[0xE9] == "eacute"
    assert 32 not in scrub.encoding_names(None)  # a TeX font's own encoding: code 32 is no space


def _quartz_font(missing=""):
    """A MacRoman subset font as Quartz writes it: every glyph 500 wide, 250 for the space, 0 for one not in it."""
    names = scrub.encoding_names("/MacRomanEncoding")
    widths = [0.0 if names.get(c, "") in ("", *missing) else 250.0 if c == 32 else 500.0 for c in range(32, 256)]
    return scrub.Font(names, widths, first=32)


def test_a_glyph_of_width_zero_is_not_in_a_subset_font_and_no_word_is_written_with_it():
    font = _quartz_font(missing="e")
    assert "e" not in font.code_for_char and "a" in font.code_for_char and "é" in font.code_for_char
    assert not font.can_write("de", [False, False])


def _advance(font, items):
    """Where each glyph starts, in thousandths of the font size, through a TJ array."""
    x, starts = 0.0, []
    for item in items:
        if isinstance(item, bytes):
            for b in item:
                starts.append((b, x))
                x += font.width(b)
        else:
            x -= item
    return starts


def test_words_between_real_spaces_are_replaced_and_each_starts_where_it_did():
    font = _quartz_font()
    original = [b"Plain words, made up here", 30.0, b"x"]
    items, owed = scrub.scrub_op(font, original, banned={"plain", "words", "made", "here"})
    text = b"".join(x for x in items if isinstance(x, bytes)).decode("mac_roman")
    assert text.count(" ") == 4 and "," in text
    assert not {"plain", "words", "made", "here", "up"} & set(text.lower().replace(",", " ").split())
    space_at = lambda its: [x for b, x in _advance(font, its) if b == 32]  # noqa: E731
    assert space_at(items) == pytest.approx(space_at(original))


def test_a_number_becomes_other_digits_none_of_the_originals_numbers_inside_it():
    font = _quartz_font()
    banned = {"12", "34", "56", "1234"}
    for _ in range(30):
        items, _ = scrub.scrub_op(font, [b"(+12) 34 56 1234"], banned)
        text = b"".join(x for x in items if isinstance(x, bytes)).decode("mac_roman")
        runs = re.findall(r"\d+", text)
        assert [len(r) for r in runs] == [2, 2, 2, 4]
        assert not any(b in r for r in runs for b in banned)


def test_a_word_a_little_too_wide_loses_to_a_narrower_one_so_it_does_not_run_into_the_next():
    font = _quartz_font()
    for _ in range(20):
        word = scrub.pick(font, 2350.0, "lower", banned=set(), letters=5)  # 5 letters 150 too wide, 4 are 350 short
        assert len(word) == 4


def test_a_word_no_french_word_fits_is_made_of_the_fonts_own_letters_not_dropped():
    names = scrub.encoding_names("/MacRomanEncoding")
    have = set("QXZ")
    widths = [500.0 if names.get(c) in have else 0.0 for c in range(32, 256)]
    font = scrub.Font(names, widths, first=32)
    word = scrub.pick(font, 1500.0, "upper", banned=set(), letters=3)
    assert len(word) == 3 and set(word) <= have


def test_only_the_producing_programs_names_are_kept_from_the_document_info():
    info = {"/Title": "x", "/Author": "y", "/CreationDate": "D:2000", "/Creator": "Pages", "/Producer": "Quartz"}
    assert scrub.kept_info(info) == {"/Creator": "Pages", "/Producer": "Quartz"}


_check_spec = importlib.util.spec_from_file_location("scrub_check", REPO_ROOT / "scripts" / "style_corpus" / "scrub_check.py")
scrub_check = importlib.util.module_from_spec(_check_spec)
_check_spec.loader.exec_module(scrub_check)


def test_the_bytes_searched_for_left_words_leave_out_pdf_names_and_font_programs():
    assert scrub_check.searchable(b"<</Resources 3 0 R /Type /Page>> (Resources here)").count(b"resources") == 1
    assert scrub_check.searchable(b"\x00\x01\x00\x00 glyf data") is None  # a TrueType program
    assert scrub_check.searchable(b"/CIDInit /ProcSet findresource begin") is None  # a ToUnicode CMap
    assert scrub_check.searchable(b"%!PS-AdobeFont-1.0") is None
    for accented in (b"(march\\216) Tj", b"(march\xe9) Tj"):  # an accent, escaped or not, is part of its word
        assert not re.search(rb"\bmarch\b", scrub_check.searchable(accented))


def test_an_original_number_left_is_found_inside_a_longer_one_not_across_a_break():
    assert scrub_check.numbers_left({"2016", "45", "word"}, "call 1-452 or 20 16") == ["45"]
