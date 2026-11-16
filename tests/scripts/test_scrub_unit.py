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


def test_marked_content_keeps_only_its_mcid():
    assert scrub.mcid_only({"/MCID": 4, "/ActualText": "x", "/Alt": "y"}) == {"/MCID": 4}
    assert scrub.mcid_only({"/ActualText": "x"}) == {}


def test_a_cff_font_program_and_the_structure_of_a_tagged_pdf_are_told_apart_in_the_check():
    assert scrub_check.searchable(b"\x01\x00\x04\x01 cff data") is None
    left = scrub_check.structure_left([b"<</Type /StructTreeRoot>>", b"/P <</ActualText (x) /Alt (y)>>", b"/Alternate /DeviceRGB"])
    assert left == ["/ActualText", "/Alt", "/StructTreeRoot"]


# --- whole PDFs (pikepdf, which only the scrubber's own venv has) ---

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
    assert list(bdc.keys()) == ["/MCID"]
    font = scrub.Font.from_pdf(pdf.pages[0].Resources.Font.F1)
    text = "".join(font.char_of.get(int.from_bytes(bytes(o)[k:k + 2], "big"), " ")
                   for op, operands in ops if op == "Tj" for o in operands for k in range(0, len(bytes(o)), 2))
    assert text and not {"zebra", "yacht", "quilt"} & set(text.split())


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
