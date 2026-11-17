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


def _block(*ops, font="/F1", size=10.0):
    """A text block of a simple font: Tf, a Td to (72, 700), then these operators."""
    return [("BT", []), ("Tf", [font, size]), ("Td", [72.0, 700.0]), *ops, ("ET", [])]


def _laid(font, ops, name="/F1"):
    """Each glyph of the page as (x, character, where the next glyph would start), in the order drawn."""
    out = []
    for g in scrub.glyphs_of(ops, {name: font}):
        if not isinstance(g, scrub.Glyph):
            continue
        x = g.x
        for b in g.data:
            ch = font.char_of.get(b) or (str(scrub.DIGIT_NAMES.index(font.digit_of[b])) if b in font.digit_of else chr(b))
            end = x + scrub.advance(font, g.size, g.tc, g.tw, bytes([b]))
            out.append((round(x, 3), ch, end))
            x = end
    return out


def _words(font, ops):
    """(x, word) of each word of the page: letters or digits drawn one after the other, a point apart at most."""
    found, last, end = [], None, None
    for x, ch, nxt in _laid(font, ops):
        if ch.isalnum() and last and last[1][-1:].isalnum() and abs(x - end) <= 1.0:
            last[1] += ch
        else:
            last = [x, ch]
            found.append(last)
        end = nxt
    return [(x, w) for x, w in found if w.isalnum()]


def test_words_between_real_spaces_are_replaced_and_each_starts_where_it_did():
    font = _quartz_font()
    ops = _block(("TJ", [[b"Plain words, made up here", 30.0, b"x"]]))
    new = scrub.rewrite_content(ops, {"/F1": font}, banned={"plain", "words", "made", "here"})
    text = "".join(ch for _, ch, _ in _laid(font, new))
    assert text.count(" ") == 4 and "," in text
    assert not {"plain", "words", "made", "here", "up"} & set(text.lower().replace(",", " ").split())
    space_at = lambda o: [x for x, ch, _ in _laid(font, o) if ch == " "]  # noqa: E731
    assert space_at(new) == pytest.approx(space_at(ops))
    assert [x for x, _ in _words(font, new)] == pytest.approx([x for x, _ in _words(font, ops)])


def test_pdftex_glue_ends_a_word_and_a_kern_inside_a_word_does_not():
    font = _quartz_font()  # a TeX font has no space glyph: words are set apart by kerns of 0.22-0.33 em
    ops = _block(("TJ", [[b"Pla", 40.0, b"in", -250.0, b"word", -330.0, b"here"]]))
    new = scrub.rewrite_content(ops, {"/F1": font}, banned={"plain", "word", "here"})
    before, after = _words(font, ops), _words(font, new)
    assert [w for _, w in before] == ["Plain", "word", "here"]
    assert len(after) == 3 and [x for x, _ in after] == pytest.approx([x for x, _ in before])


def test_a_line_comes_back_as_one_tj_array_its_words_apart_by_kerns_as_a_reader_finds_word_breaks():
    font = _quartz_font()  # pdfium reads pdfTeX's word breaks from the kerns of a TJ, not from gaps between Tj's
    ops = _block(("TJ", [[b"plain", -250.0, b"word", -330.0, b"here"]]))
    new = scrub.rewrite_content(ops, {"/F1": font}, banned={"plain", "word", "here"})
    shown = [args[0] for op, args in new if op in ("Tj", "TJ")]
    assert len(shown) == 1 and [x for x in shown[0] if not isinstance(x, bytes)] == pytest.approx([-250.0, -330.0], abs=60)
    assert [x for x, _ in _words(font, new)] == pytest.approx([x for x, _ in _words(font, ops)])


def test_punctuation_right_after_a_word_moves_with_the_word_s_end_and_the_next_word_stays():
    names = scrub.encoding_names("/MacRomanEncoding")
    widths = [900.0 if names.get(c) == "x" else 250.0 if c in (32, 44) else 500.0 for c in range(32, 256)]
    font = scrub.Font(names, widths, first=32)  # "xx" is 1800 wide, any French two-letter word 1000
    ops = _block(("Tj", [b"xx, ab"]))
    new = scrub.rewrite_content(ops, {"/F1": font}, banned={"xx", "ab"})
    laid = _laid(font, new)
    comma = next(x for x, ch, _ in laid if ch == ",")
    assert comma == pytest.approx(72.0 + 10.0)  # right after the new word, not where the original's end left it
    assert _words(font, new)[1][0] == pytest.approx(_words(font, ops)[1][0])


@pytest.mark.parametrize("token", [b"xx.xx", b"xx-xx", b"(xx)", b"xx@xx;xx"])
def test_a_token_of_words_and_marks_stays_one_token_with_no_gap_inside(token):
    names = scrub.encoding_names("/MacRomanEncoding")
    widths = [900.0 if names.get(c) == "x" else 250.0 if c in (32, 44) else 500.0 for c in range(32, 256)]
    font = scrub.Font(names, widths, first=32)  # each "xx" (1800) becomes a word of 1000: the rest follows it
    ops = _block(("Tj", [token + b" ab"]))
    new = scrub.rewrite_content(ops, {"/F1": font}, banned={"xx", "ab"})
    laid = _laid(font, new)
    inside = laid[:[ch for _, ch, _ in laid].index(" ")]
    assert all(x == pytest.approx(end) for (_, _, end), (x, _, _) in zip(inside, inside[1:]))  # read as one token
    assert _words(font, new)[-1][0] == pytest.approx(_words(font, ops)[-1][0])  # the next word stays


def test_a_mark_set_in_a_block_of_its_own_still_follows_its_word():
    names = scrub.encoding_names("/MacRomanEncoding")
    widths = [900.0 if names.get(c) == "x" else 500.0 for c in range(32, 256)]
    font = scrub.Font(names, widths, first=32)  # Quartz starts a new block (and Tm) where the colour or link changes
    block = lambda x, text: [("BT", []), ("Tf", ["/F1", 10.0]), ("Tm", [1.0, 0.0, 0.0, 1.0, x, 700.0]),  # noqa: E731
                             ("Tj", [text]), ("ET", [])]
    ops = block(72.0, b"xx") + [("rg", [1.0, 0.0, 0.0])] + block(90.0, b"]")
    new = scrub.rewrite_content(ops, {"/F1": font}, banned={"xx"})
    glyphs = [g for g in scrub.glyphs_of(new, {"/F1": font}) if isinstance(g, scrub.Glyph)]
    word = [g for g in glyphs if g.tm[4] == 72.0]
    word_end = 72.0 + word[-1].x + scrub.advance(font, 10.0, 0.0, 0.0, word[-1].data)
    assert word_end < 90.0 and glyphs[-1].tm[4] + glyphs[-1].x == pytest.approx(word_end)


def _at(font, ops):
    """(x, y) of each glyph as glyphs_of places it."""
    return [(round(g.x, 3), round(g.y, 3)) for g in scrub.glyphs_of(ops, {"/F1": font}) if isinstance(g, scrub.Glyph)]


def test_t_star_moves_to_the_next_line_by_the_leading_tl_sets():
    ops = _block(("TL", [12.0]), ("Tj", [b"a"]), ("T*", []), ("Tj", [b"b"]))
    assert _at(_quartz_font(), ops) == [(72.0, 700.0), (72.0, 688.0)]


def test_td_with_a_capital_moves_like_td_and_sets_the_leading():
    ops = _block(("TD", [0.0, -14.0]), ("Tj", [b"b"]), ("T*", []), ("Tj", [b"c"]))
    assert _at(_quartz_font(), ops) == [(72.0, 686.0), (72.0, 672.0)]


def test_word_spacing_widens_the_space_code_only():
    ops = _block(("Tw", [3.0]), ("Tj", [b"a b"]))
    assert _at(_quartz_font(), ops) == [(72.0, 700.0), (77.0, 700.0), (82.5, 700.0)]


def test_word_spacing_does_not_widen_a_two_byte_font_s_code_32():
    font = _type0_font()
    ops = _block(("Tw", [3.0]), ("Tj", [(32).to_bytes(2, "big") + (1).to_bytes(2, "big")]))
    assert [x for x, _ in _at(font, ops)] == [72.0, 77.0]


def test_a_quote_moves_to_the_next_line_and_shows_its_string():
    ops = _block(("TL", [12.0]), ("'", [b"b"]))
    assert _at(_quartz_font(), ops) == [(72.0, 688.0)]


def test_a_double_quote_sets_word_and_character_spacing_then_moves_to_the_next_line():
    ops = _block(("TL", [12.0]), ('"', [2.0, 1.0, b"a b"]))
    assert _at(_quartz_font(), ops) == [(72.0, 688.0), (78.0, 688.0), (83.5, 688.0)]


def test_lines_set_by_t_star_and_quotes_keep_their_words_where_they_were():
    font = _quartz_font()
    ops = _block(("TL", [12.0]), ("Tw", [3.0]), ("Tj", [b"plain word"]), ("'", [b"here now"]), ('"', [1.0, 0.5, b"made up"]))
    new = scrub.rewrite_content(ops, {"/F1": font}, banned={"plain", "word", "here", "now", "made"})
    lines = lambda o: sorted({y for _, y in _at(font, o)})  # noqa: E731
    assert lines(new) == lines(ops) == [676.0, 688.0, 700.0]
    assert [w for _, w in _words(font, new)] != [w for _, w in _words(font, ops)]
    assert [w[0] for w in _words(font, new)] == pytest.approx([w[0] for w in _words(font, ops)])


def test_letter_spaced_text_keeps_its_spacing_and_its_words_their_starts():
    font = _quartz_font()  # Tc of a whole em, as a spaced-out heading: still one word
    ops = _block(("Tc", [10.0]), ("Tj", [b"HEAD"]), ("Tj", [b" "]), ("Tj", [b"LINE"]))
    new = scrub.rewrite_content(ops, {"/F1": font}, banned={"head", "line"})
    before, after = _words(font, ops), _words(font, new)
    assert [w for _, w in before] == ["HEAD", "LINE"] and len(after) == 2
    assert [x for x, _ in after] == pytest.approx([x for x, _ in before])
    assert all(len(w) <= 5 for _, w in after)  # the spacing is not filled with letters


def test_character_spacing_ends_with_the_graphics_state_it_was_set_in():
    font = _quartz_font()
    ops = [("q", []), *_block(("Tc", [1.0]), ("Tj", [b"ab"])), ("Q", []), *_block(("Tj", [b"ab"]))]
    xs = [x for x, _, _ in _laid(font, ops)]
    assert xs == pytest.approx([72.0, 78.0, 72.0, 77.0])


def test_every_text_block_sets_its_font_as_a_q_before_it_may_have_dropped_the_last_one():
    font = _quartz_font()  # pdfTeX: q BT Tm Tf TJ ET Q, block after block in the same font
    block = [("q", []), ("BT", []), ("Tm", [1.0, 0.0, 0.0, 1.0, 72.0, 700.0]), ("Tf", ["/F1", 10.0]),
             ("TJ", [[b"x"]]), ("ET", []), ("Q", [])]
    new = scrub.rewrite_content(block + block, {"/F1": font}, set())
    assert [op for op, _ in new].count("Tf") == 2


def test_a_number_becomes_other_digits_none_of_the_originals_numbers_inside_it():
    font = _quartz_font()
    banned = {"12", "34", "56", "1234"}
    for _ in range(30):
        new = scrub.rewrite_content(_block(("Tj", [b"(+12) 34 56 1234"])), {"/F1": font}, banned)
        runs = re.findall(r"\d+", "".join(ch for _, ch, _ in _laid(font, new)))
        assert [len(r) for r in runs] == [2, 2, 2, 4]
        assert not any(b in r for r in runs for b in banned)


def test_a_word_a_little_too_wide_loses_to_a_narrower_one_so_it_does_not_run_into_the_next():
    font = _quartz_font()
    for _ in range(20):
        word = scrub.pick(font, 2350.0, "lower", banned=set(), letters=5)  # 5 letters 150 too wide, 4 are 350 short
        assert len(word) == 4


def _narrow_font(narrow="ILiltf"):
    """A MacRoman font where these letters are narrow (280), the space 250 and every other letter wide (700)."""
    names = scrub.encoding_names("/MacRomanEncoding")
    narrow = set(narrow)
    widths = [280.0 if names.get(c) in narrow else 250.0 if c == 32 else 0.0 if c < 65 else 700.0 for c in range(32, 256)]
    return scrub.Font(names, widths, first=32)


@pytest.mark.parametrize("case", ["lower", "title", "upper"])
def test_a_one_letter_word_becomes_one_letter_even_when_two_narrow_ones_fit_its_width_better(case):
    for _ in range(20):  # "Il" (560) is nearer a narrow "I" (280) than "A" or "y" (700) is
        assert len(scrub.pick(_narrow_font(), 280.0, case, banned=set(), letters=1)) == 1


def test_a_narrow_one_letter_word_becomes_another_narrow_letter_so_it_does_not_run_into_the_next_word():
    font = _narrow_font()
    for _ in range(20):
        new = scrub.rewrite_content(_block(("Tj", [b"I see"])), {"/F1": font}, banned={"see"})
        first = "".join(ch for _, ch, _ in _laid(font, new)).split(" ")[0]
        assert first == "L"  # as narrow as "I", and not the original letter


def test_a_narrow_capital_no_other_capital_is_as_narrow_as_becomes_a_narrow_small_letter():
    font = _narrow_font("Iil")  # as Avenir: I 260, J 492, i and l 250
    for _ in range(20):
        assert scrub.pick(font, 280.0, "upper", banned={"i"}, letters=1) == "l"


def test_a_one_letter_word_no_french_one_letter_word_can_write_is_one_of_the_fonts_own_letters():
    names = scrub.encoding_names("/MacRomanEncoding")
    have = set("Ilnu")  # no a, y or à in the subset, but "il", "un", "nu" are
    widths = [500.0 if names.get(c) in have else 0.0 for c in range(32, 256)]
    font = scrub.Font(names, widths, first=32)
    word = scrub.pick(font, 500.0, "title", banned=set(), letters=1)
    assert len(word) == 1 and word in have


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


# --- Type0 (Word, Skia) and Type3 fonts ---

CMAP = b"""/CIDInit /ProcSet findresource begin 12 dict begin begincmap
1 begincodespacerange <0000> <FFFF> endcodespacerange
2 beginbfchar
<0003> <0020>
<0010> <00E9>
endbfchar
2 beginbfrange
<0020> <0022> <0061>
<0030> <0031> [<0066> <00660069>]
endbfrange
endcmap end end"""


def test_a_tounicode_cmap_maps_codes_by_char_by_range_and_by_array_with_multi_char_values_kept():
    got = scrub.parse_tounicode(CMAP.decode())
    assert got == {3: " ", 0x10: "é", 0x20: "a", 0x21: "b", 0x22: "c", 0x30: "f", 0x31: "fi"}


def test_a_w_array_reads_both_forms():
    assert scrub.parse_w([3, [500.0, 600.0], 10, 12, 700.0]) == {3: 500.0, 4: 600.0, 10: 700.0, 11: 700.0, 12: 700.0}


LETTERS = "abcdefghijklmnopqrstuvwxyz"


def _type0_font(missing=""):
    """A two-byte font as Word or Skia write it: codes 1-26 the letters, 27-36 the digits, 40 the space; the codes
    not in /W (the letters of `missing`) are not in the subset."""
    chars = {i + 1: ch for i, ch in enumerate(LETTERS)} | {27 + d: str(d) for d in range(10)} | {40: " ", 50: "ﬁ"}
    chars[50] = "fi"
    width = {c: 250.0 if c == 40 else 500.0 for c in chars}
    codes = {c for c, ch in chars.items() if ch not in missing}
    return scrub.Font.from_unicode(chars, lambda c: width.get(c, 1000.0), 2, codes)


def test_a_two_byte_font_writes_two_byte_codes_of_the_letters_in_its_subset_and_never_a_ligature():
    font = _type0_font(missing="e")
    assert font.code_len == 2
    assert "e" not in font.code_for_char and font.code_for_char["a"] == 1 and font.space_codes == {40}
    assert font.char_of[50] == "f" and 50 not in font.code_for_char.values()  # a ligature is read, never written
    assert font.digit_of[27] == "zero" and font.width(1) == 500.0 and font.width(999) == 1000.0


def _skia_ops(font, text, size=10.0, y=100.0):
    """One glyph per Tj, an absolute-looking Td before each, as Skia writes them."""
    code = {"abcdefghijklmnopqrstuvwxyz"[i]: i + 1 for i in range(26)} | {str(d): 27 + d for d in range(10)} | {" ": 40, ",": 99}
    ops, x = [("BT", []), ("Tf", ["/F1", size]), ("Tm", [1.0, 0.0, 0.0, -1.0, 40.0, y])], 0.0
    for k, ch in enumerate(text):
        if k:
            ops.append(("Td", [font.width(code[text[k - 1]]) * size / 1000, 0.0]))
        ops.append(("Tj", [code[ch].to_bytes(2, "big")]))
    return ops + [("ET", [])]


def _starts(font, ops):
    """(x, text) of each word of the page, the space glyphs between them."""
    out, word = [], None
    for g in scrub.glyphs_of(ops, {"/F1": font}):
        if not isinstance(g, scrub.Glyph):
            continue
        for i in range(0, len(g.data), 2):
            c = int.from_bytes(g.data[i:i + 2], "big")
            if c in font.space_codes:
                word = None
                continue
            ch = str(scrub.DIGIT_NAMES.index(font.digit_of[c])) if c in font.digit_of else font.char_of.get(c, ",")
            if word is None:
                word = [round(g.x, 3), ""]
                out.append(word)
            word[1] += ch
    return [tuple(w) for w in out]


def test_a_skia_text_block_has_each_word_replaced_and_each_starting_where_it_did():
    font = _type0_font()
    ops = _skia_ops(font, "plain words, made 2024 here")
    banned = {"plain", "words", "made", "here", "2024"}
    new = scrub.rewrite_content(ops, {"/F1": font}, banned)
    before, after = _starts(font, ops), _starts(font, new)
    assert [x for x, _ in after] == [x for x, _ in before]
    said = " ".join(t for _, t in after)
    assert not banned & set(said.replace(",", " ").split())
    assert re.search(r"\d{4}", said) and "2024" not in said and "," in said
    assert [op for op, _ in new if op == "Tm"] == ["Tm"]


def test_a_one_letter_word_of_a_skia_block_never_comes_back_as_itself():
    font = _type0_font()  # every letter as wide: the original letter would fit best
    ops = _skia_ops(font, "a b")
    for _ in range(20):
        words = [t for _, t in _starts(font, scrub.rewrite_content(ops, {"/F1": font}, set()))]
        assert len(words) == 2 and words[0] != "a" and words[1] != "b"


def test_a_word_text_block_of_tj_arrays_with_real_spaces_is_laid_out_the_same_way():
    font = _type0_font()
    code = lambda s: b"".join(({" ": 40}.get(ch) or "abcdefghijklmnopqrstuvwxyz".index(ch) + 1).to_bytes(2, "big") for ch in s)  # noqa: E731
    ops = [("BT", []), ("Tf", ["/F1", 11.0]), ("Td", [72.0, 700.0]),
           ("TJ", [[code("plain"), -20.0, code("words"), code(" "), code("here")]]), ("ET", [])]
    new = scrub.rewrite_content(ops, {"/F1": font}, {"plain", "words", "here"})
    said = " ".join(t for _, t in _starts(font, new))
    assert not {"plain", "words", "here"} & set(said.split())
    assert [x for x, _ in _starts(font, new)] == [x for x, _ in _starts(font, ops)]


def test_text_in_a_font_with_no_codes_to_unicode_is_left_alone_and_other_operators_stay_in_place():
    font = scrub.Font.from_unicode({}, lambda c: 500.0, 1)
    ops = [("q", []), ("BT", []), ("Tf", ["/F1", 10.0]), ("rg", [1.0, 0.0, 0.0]), ("Tj", [b"\x01"]), ("ET", []), ("Q", [])]
    new = scrub.rewrite_content(ops, {"/F1": font}, set())
    assert [op for op, _ in new if op not in ("Tf", "Td", "Tm")] == ["q", "BT", "rg", "Tj", "ET", "Q"]
    assert [x for op, x in new if op == "Tj"] == [[b"\x01"]]


def test_a_letter_beyond_french_is_part_of_its_word_and_goes_with_it():
    chars = {i + 1: ch for i, ch in enumerate(LETTERS)} | {60: "ő", 61: "Ő", 40: " "}
    font = scrub.Font.from_unicode(chars, lambda c: 500.0, 2)
    assert font.char_of[60] == "ő" and font.char_of[61] == "Ő" and 60 not in font.code_for_char.values()
    code = lambda cs: b"".join(c.to_bytes(2, "big") for c in cs)  # noqa: E731
    ops = [("BT", []), ("Tf", ["/F1", 10.0]), ("Td", [10.0, 10.0]),
           ("Tj", [code([19, 26, 60, 11, 5])]), ("ET", [])]  # s z ő k e
    new = scrub.rewrite_content(ops, {"/F1": font}, {"szőke"})
    text = "".join(font.char_of[int.from_bytes(d[i:i + 2], "big")] for op, args in new if op == "Tj" for d in args for i in range(0, len(d), 2))
    assert text and "ő" not in text and text != "szőke"  # one word replaced whole, not "Se", "ő", "kk"


def test_a_cff_font_program_and_the_structure_of_a_tagged_pdf_are_told_apart_in_the_check():
    assert scrub_check.searchable(b"\x01\x00\x04\x01 cff data") is None
    left = scrub_check.structure_left([b"<</Type /StructTreeRoot>>", b"/P <</ActualText (x) /Alt (y)>>", b"/Alternate /DeviceRGB"])
    assert left == ["/ActualText", "/Alt", "/StructTreeRoot"]


# --- whole PDFs (pikepdf, which only the scrubber's own venv has) ---

def _shown(op, operands):
    """The strings a Tj or a TJ shows, as bytes."""
    import pikepdf

    items = {"Tj": lambda: [operands[0]], "TJ": lambda: list(operands[0])}.get(str(op), list)()
    return [bytes(x) for x in items if isinstance(x, pikepdf.String)]


def _word_like_pdf(path):
    """A tagged PDF with a fontless Type0 font as Word writes one: hex codes in TJ arrays, a ToUnicode, an Author."""
    pikepdf = pytest.importorskip("pikepdf")
    pdf = pikepdf.new()
    cmap = ("1 begincodespacerange <0000> <FFFF> endcodespacerange\\n"
            "1 beginbfrange\\n<0001> <001A> <0061>\\nendbfrange\\n1 beginbfchar\\n<0028> <0020>\\nendbfchar")
    desc = pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.CIDFontType2, BaseFont=pikepdf.Name("/AAAAAA+Test"),
                              CIDSystemInfo=pikepdf.Dictionary(Registry=pikepdf.String("Adobe"), Ordering=pikepdf.String("Identity"), Supplement=0),
                              DW=500, W=pikepdf.Array([1, 26, 500, 40, pikepdf.Array([250])]))
    font = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type0, BaseFont=pikepdf.Name("/AAAAAA+Test"), Encoding=pikepdf.Name("/Identity-H"),
        DescendantFonts=pikepdf.Array([pdf.make_indirect(desc)]), ToUnicode=pdf.make_stream(cmap.encode())))
    codes = lambda s: "".join("%04X" % (0x28 if ch == " " else ord(ch) - 96) for ch in s)  # noqa: E731
    content = (f"/P <</MCID 0 /ActualText (zebra) /Alt (zebra)>> BDC BT /F1 11 Tf 72 700 Td "
               f"[<{codes('zebra')}> -10 <{codes('yacht')}> <{codes(' ')}> <{codes('quilt')}>] TJ ET EMC")
    page = pdf.add_blank_page(page_size=(300, 800))
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    page.Contents = pdf.make_stream(content.encode())
    pdf.Root.StructTreeRoot = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
    pdf.Root.MarkInfo, pdf.Root.Lang = pikepdf.Dictionary(Marked=True), pikepdf.String("en")
    pdf.docinfo["/Author"] = "Zebra Yacht"
    pdf.save(path)


def test_a_word_like_pdf_loses_its_words_its_structure_and_its_author(tmp_path):
    pikepdf = pytest.importorskip("pikepdf")
    src, dst, words = tmp_path / "in.pdf", tmp_path / "out.pdf", tmp_path / "w.json"
    _word_like_pdf(src)
    words.write_text('["zebra", "yacht", "quilt"]')
    scrub.main(str(src), str(dst), str(words))
    pdf = pikepdf.open(dst)
    assert not {"/StructTreeRoot", "/MarkInfo", "/Lang"} & set(pdf.Root.keys()) and "/Author" not in (pdf.trailer.get("/Info") or {})
    ops = [(str(op), operands) for operands, op in pikepdf.parse_content_stream(pdf.pages[0])]
    bdc = [operands[1] for op, operands in ops if op == "BDC"][0]
    assert list(bdc.keys()) == ["/MCID"]  # /ActualText and /Alt gone
    font = scrub.Font.from_pdf(pdf.pages[0].Resources.Font.F1)
    text = "".join(font.char_of.get(int.from_bytes(bytes(o)[k:k + 2], "big"), " ")
                   for op, operands in ops for o in _shown(op, operands) for k in range(0, len(o), 2))
    assert text and not {"zebra", "yacht", "quilt"} & set(text.split())


def test_a_word_like_pdf_loses_links_form_text_and_named_marked_content_properties_too(tmp_path):
    pikepdf = pytest.importorskip("pikepdf")
    src, dst, words = tmp_path / "in.pdf", tmp_path / "out.pdf", tmp_path / "w.json"
    _word_like_pdf(src)
    pdf = pikepdf.open(src, allow_overwriting_input=True)
    page = pdf.pages[0]
    link = pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link, Rect=[0, 0, 10, 10],
                              A=pikepdf.Dictionary(S=pikepdf.Name.URI, URI=pikepdf.String("mailto:zebra@example.com")))
    page.Annots = pikepdf.Array([pdf.make_indirect(link)])
    page.StructParents = 0
    page.Resources.Properties = pikepdf.Dictionary(P0=pikepdf.Dictionary(MCID=1, ActualText=pikepdf.String("zebra secret")))
    code = "".join("%04X" % (ord(ch) - 96) for ch in "quilt")
    form = pdf.make_stream(f"BT /F1 11 Tf 72 600 Td <{code}> Tj ET".encode())
    form.Type, form.Subtype, form.BBox = pikepdf.Name.XObject, pikepdf.Name.Form, [0, 0, 300, 800]
    form.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=page.Resources.Font.F1))
    page.Resources.XObject = pikepdf.Dictionary(X0=form)
    page.Contents = pdf.make_stream(page.Contents.read_bytes() + b" /Span /P0 BDC EMC /X0 Do")
    pdf.save(src)
    words.write_text('["zebra", "yacht", "quilt"]')
    scrub.main(str(src), str(dst), str(words))
    result = pikepdf.open(dst)
    out = result.pages[0]
    assert "/Annots" not in out and "/StructParents" not in out
    assert list(out.Resources.Properties.P0.keys()) == ["/MCID"]
    font = scrub.Font.from_pdf(out.Resources.Font.F1)
    codes = [int.from_bytes(o[k:k + 2], "big") for operands, op in pikepdf.parse_content_stream(out.Resources.XObject.X0)
             for o in _shown(op, operands) for k in range(0, len(o), 2)]
    assert codes and "quilt" != "".join(font.char_of.get(c, " ") for c in codes)


STYLES = REPO_ROOT / "tests" / "tailoring" / "fixtures" / "styles"


@pytest.mark.parametrize("name", ["html-word-two-column.pdf", "html-canva-icons.pdf"])
def test_a_skia_pdf_keeps_its_layout_and_loses_the_words_it_had(tmp_path, name):
    pytest.importorskip("pikepdf")
    pdfium = pytest.importorskip("pypdfium2")
    src, dst, words = STYLES / name, tmp_path / "out.pdf", tmp_path / "w.json"
    text = "\n".join(p.get_textpage().get_text_range() for p in pdfium.PdfDocument(str(src)))
    original = sorted({w.lower() for w in re.findall(scrub_check.WORD, text)})
    words.write_text(__import__("json").dumps(original))
    scrub.main(str(src), str(dst), str(words))
    after = "\n".join(p.get_textpage().get_text_range() for p in pdfium.PdfDocument(str(dst))).lower()
    assert len(original) > 10 and not set(original) & set(re.findall(scrub_check.WORD, after))
    assert len(pdfium.PdfDocument(str(dst))) == len(pdfium.PdfDocument(str(src)))


def test_runs_joined_into_words_are_judged_by_where_they_start_among_the_original_starts():
    assert scrub_check.shift([(0.0, 5.0), (3.0, 5.0), (6.0, 5.0)], [(3.0, 5.0)]) == \
        "count changed 3 -> 1, each new run starts at most 0.000 pt from an original one"
    assert scrub_check.shift([(0.0, 5.0)], [(0.0, 5.5)]) == "0.500 pt"


# ----------------------------------------------------------------------------- the colours go too
@pytest.mark.parametrize("colour", [(0.2, 0.4, 0.9), (0.1, 0.1, 0.45), (0.8, 0.1, 0.05), (0.95, 0.85, 0.1)])
@pytest.mark.parametrize("turn", [120, 180, 240])
def test_a_colour_turns_round_the_wheel_keeping_how_light_it_looks(colour, turn):
    """Its contrast with the page stays: a blue heading never turns into a pale yellow one."""
    import colorsys
    turned = scrub.turn_colour(colour, turn)
    h0, _, _ = colorsys.rgb_to_hls(*colour)
    h1, _, _ = colorsys.rgb_to_hls(*turned)
    assert abs(((h1 - h0) * 360) % 360 - turn) < 3
    assert abs(scrub.luminance(turned) - scrub.luminance(colour)) < 0.01


@pytest.mark.parametrize("grey", [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.3, 0.3, 0.3), (0.3, 0.302, 0.301)])
def test_a_grey_black_or_white_stays(grey):
    assert scrub.turn_colour(grey, 120) == grey


def test_a_grey_with_a_tint_turns_too():
    tinted = (0.5, 0.53, 0.54)
    assert scrub.turn_colour(tinted, 120) != tinted


def test_every_rgb_fill_and_stroke_is_turned_and_nothing_else():
    ops = [([0.1, 0.1, 0.45], "rg"), ([0.1, 0.1, 0.45], "RG"), ([0.2, 0.5, 0.6], "sc"), ([0.2, 0.5, 0.6], "SCN"),
           ([0.5], "sc"), ([0.4], "g"), ([1, 0, 0, 1, 10, 20], "cm"), ([0.0, 0.0, 0.0], "rg")]
    out = scrub.recolour_ops(ops, 90)
    assert [o for _, o in out] == [o for _, o in ops]
    assert all(out[i][0] != ops[i][0] for i in range(4))
    assert out[4:] == ops[4:]


def test_a_colour_it_cannot_turn_is_counted():
    """CMYK, a shading, a pattern's colour: left as they are, so the scrub says how many to look at."""
    ops = [([0.1, 0.1, 0.45], "rg"), ([0, 0.5, 1, 0], "k"), ([0, 0.5, 1, 0], "K"), (["/Sh1"], "sh"),
           ([0.1, 0.2, 0.3, "/P1"], "scn"), (["/P1"], "scn"), ([0.4], "g")]
    assert scrub.colours_left(ops) == 5


def test_a_whole_pdf_has_its_page_and_form_colours_turned():
    pikepdf = pytest.importorskip("pikepdf")
    pdf = pikepdf.new()
    form = pdf.make_stream(b"0.8 0.1 0.05 rg 0 0 5 5 re f", Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Form,
                           BBox=[0, 0, 10, 10])
    pdf.add_blank_page()
    page = pdf.pages[0]
    page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(F1=form))
    page.Contents = pdf.make_stream(b"0.1 0.1 0.45 RG 0.3 g /F1 Do")
    assert scrub.recolour(pdf, 180) == 0
    colours = [(str(op), [float(x) for x in o]) for obj in (page, form) for o, op in pikepdf.parse_content_stream(obj)
               if str(op) in ("rg", "RG", "g")]
    assert [c for c, _ in colours] == ["RG", "g", "rg"]
    assert colours[0][1] != [0.1, 0.1, 0.45] and colours[1][1] == [0.3] and colours[2][1] != [0.8, 0.1, 0.05]


def test_a_simple_font_pdf_loses_the_text_of_its_forms_too_and_keeps_its_icons(tmp_path):
    pikepdf = pytest.importorskip("pikepdf")
    src, dst, words = tmp_path / "in.pdf", tmp_path / "out.pdf", tmp_path / "w.json"
    pdf = pikepdf.new()
    widths = pikepdf.Array([500] * 224)
    text = pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.TrueType, BaseFont=pikepdf.Name("/AAAAAA+Test"),
                              Encoding=pikepdf.Name.MacRomanEncoding, FirstChar=32, LastChar=255, Widths=widths)
    icons = pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name("/BBBBBB+FontAwesome"),
                               FirstChar=32, LastChar=255, Widths=widths)
    fonts = pikepdf.Dictionary(F1=pdf.make_indirect(text), FA=pdf.make_indirect(icons))
    form = pdf.make_stream(b"BT /F1 11 Tf 72 600 Td (quilt) Tj ET")
    form.Type, form.Subtype, form.BBox = pikepdf.Name.XObject, pikepdf.Name.Form, [0, 0, 300, 800]
    form.Resources = pikepdf.Dictionary(Font=fonts)
    page = pdf.add_blank_page(page_size=(300, 800))
    page.Resources = pikepdf.Dictionary(Font=fonts, XObject=pikepdf.Dictionary(X0=form))
    page.Contents = pdf.make_stream(b"BT /F1 11 Tf 72 700 Td [(zebra) -250 (yacht)] TJ /FA 11 Tf 0 -20 Td (gh) Tj ET /X0 Do")
    pdf.save(src)
    words.write_text('["zebra", "yacht", "quilt"]')
    scrub.main(str(src), str(dst), str(words))
    result = pikepdf.open(dst)
    out = result.pages[0]

    def shown(stream):
        found, font = [], None
        for operands, op in pikepdf.parse_content_stream(stream):
            if str(op) == "Tf":
                font = str(operands[0])
            else:
                found += [(font, o.decode("mac_roman")) for o in _shown(op, operands)]
        return found

    page_text, form_text = shown(out), shown(out.Resources.XObject.X0)
    assert [t for f, t in page_text if f == "/FA"] == ["gh"]  # icons: codes of their own font, not letters
    said = " ".join(t for f, t in page_text + form_text if f == "/F1")
    assert form_text and said and not {"zebra", "yacht", "quilt"} & set(said.lower().split())
