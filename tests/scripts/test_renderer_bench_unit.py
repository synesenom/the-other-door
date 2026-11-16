"""scripts/renderer_bench.py: the pure parts of the renderer bench (#145): timing, the French typography and
hyphenation check, the font and icon checks, the access verdict, the choice rule and the table."""

import importlib.util

from PIL import Image

from paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("renderer_bench", REPO_ROOT / "scripts" / "renderer_bench.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)

# a one-page PDF written by hand: a red rectangle (10,10 50x20 from the bottom left) and a line of Helvetica
_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 110>>stream
1 0 0 rg 10 10 50 20 re f
0 0 1 rg BT /F1 14 Tf 20 150 Td (Hello World) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
trailer<</Root 1 0 R>>
%%EOF
"""


def _pdf(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(_PDF)
    return pdf


# ---------- timing ----------

def test_timing_is_one_cold_run_then_the_median_of_the_warm_ones():
    calls = []
    out = bench.timing(lambda: calls.append(1), runs=3)
    assert len(calls) == 4
    assert set(out) == {"cold", "warm"} and out["cold"] >= 0 and out["warm"] >= 0


def test_timing_warm_is_the_median(monkeypatch):
    ticks = iter([0, 9, 10, 11, 20, 23, 30, 36])  # run lengths 9, 1, 3, 6
    monkeypatch.setattr(bench.time, "perf_counter", lambda: next(ticks))
    assert bench.timing(lambda: None, runs=3) == {"cold": 9, "warm": 3}


# ---------- French typography and hyphenation ----------

NB = " "


def test_french_typography_accepts_non_breaking_spaces():
    assert bench.french_typography(f"Il a dit{NB}: «{NB}oui{NB}» et{NB}; vraiment{NB}! Quoi{NB}?") == []
    assert bench.french_typography("Où ? Si !") == []


def test_french_typography_flags_plain_and_missing_spaces():
    found = bench.french_typography("Il a dit : oui; vraiment!")
    assert any("plain space before :" in f for f in found)
    assert any("no space before ;" in f for f in found)
    assert any("no space before !" in f for f in found)


def test_french_typography_flags_a_line_that_starts_with_the_mark_and_plain_guillemet_spaces():
    found = bench.french_typography("un mot\n: la suite\n« oui »")
    assert any("line starts with :" in f for f in found)
    assert any("plain space inside «" in f for f in found) and any("plain space inside »" in f for f in found)


def test_french_typography_leaves_times_and_addresses_alone():
    assert bench.french_typography("à 12:30, voir https://example.com") == []


def test_french_typography_flags_straight_quotes():
    assert "straight quotes" in bench.french_typography('Il a dit "oui"')


def test_hyphenates():
    assert bench.hyphenates("l'anticonstitution-\nnellement")
    assert bench.hyphenates("anti­constitution")
    assert not bench.hyphenates("un mot - un autre\nligne")


# ---------- fonts ----------

def test_fonts_ok():
    assert bench.fonts_ok(["ABCDEF+Lato-Regular", "Lato-Bold"])
    assert not bench.fonts_ok(["ABCDEF+Lato-Regular", "DejaVuSans"])  # a fallback stood in
    assert not bench.fonts_ok(["Helvetica"])
    assert not bench.fonts_ok([])
    assert bench.fonts_ok(["XYZ+Figtree-Regular", "YoungSerif-Regular"], wanted=["Figtree", "Young Serif"])


def test_embedded_fonts_reads_the_pdf(tmp_path):
    assert bench.embedded_fonts(_pdf(tmp_path)) == ["Helvetica"]


# ---------- icons ----------

def _style(*shapes):
    return {"pages": [{"size": [595, 842], "texts": [], "images": [], "shapes": list(shapes)}]}


def _shape(bbox, fill=(11, 114, 133)):
    return {"bbox": bbox, "d": "", "fill": list(fill), "stroke": None, "stroke_width": 0}


EXPECTED = [{"name": "pin", "fill": [11, 114, 133], "bbox": [36, 36, 48, 48]}]


def test_icons_ok_when_fill_position_and_size_match():
    assert bench.icons_ok(_style(_shape([36.4, 35.6, 48.3, 47.9])), EXPECTED) == []


def test_icons_ok_names_what_is_wrong():
    assert bench.icons_ok(_style(), EXPECTED) == ["pin: no shape drawn"]
    assert "wrong fill" in bench.icons_ok(_style(_shape([36, 36, 48, 48], fill=(0, 0, 0))), EXPECTED)[0]
    off = bench.icons_ok(_style(_shape([40, 40, 52, 52])), EXPECTED)[0]
    assert "pin" in off and "[40, 40, 52, 52]" in off
    assert "size" in bench.icons_ok(_style(_shape([36, 36, 60, 60])), EXPECTED)[0] or "[36, 36, 60, 60]" in bench.icons_ok(_style(_shape([36, 36, 60, 60])), EXPECTED)[0]


def test_expected_icons_are_the_placed_squares():
    icons = bench.expected_icons()
    assert [i["name"] for i in icons] == ["mail", "phone", "web", "pin"]
    assert all(i["bbox"][2] - i["bbox"][0] == bench.ICON_SIZE == i["bbox"][3] - i["bbox"][1] for i in icons)


def test_icon_crop_score():
    white, black = Image.new("RGB", (100, 100), "white"), Image.new("RGB", (100, 100), "black")
    box = [[10, 10, 30, 30]]
    assert bench.icon_crop_score(black, black, box, scale=1.0) == 1.0
    assert bench.icon_crop_score(white, black, box, scale=1.0) < 0.2


# ---------- access ----------

def test_access_verdict():
    ok = {"sibling_font": True, "sibling_icon": True, "outside_file": False, "outside_url": False}
    assert bench.access_verdict(ok) == {"pass": True, "problems": []}
    leak = bench.access_verdict({**ok, "outside_file": True})
    assert not leak["pass"] and "a file outside the folder was read" in leak["problems"]
    blocked = bench.access_verdict({**ok, "sibling_icon": False, "outside_url": True})
    assert not blocked["pass"] and len(blocked["problems"]) == 2


# ---------- scoring a PDF ----------

def test_score_candidate(tmp_path):
    pdf = _pdf(tmp_path)
    ref = bench.pages_png(pdf, tmp_path / "ref")
    out = bench.score_candidate(pdf, ref, tmp_path / "work", name="Hello", headings=[], keywords=["World"],
                                wanted_font="Lato", expected=EXPECTED)
    assert out["pages"] == 1 and out["score"] > 0.99
    assert out["fonts"] is False and out["fonts_found"] == ["Helvetica"]
    assert out["icons"] == ["pin: no shape drawn"]
    assert not any(p["kind"] == "missing" for p in out["readability"])


def test_score_candidate_counts_a_missing_page_as_zero(tmp_path):
    pdf = _pdf(tmp_path)
    ref = bench.pages_png(pdf, tmp_path / "ref")
    out = bench.score_candidate(pdf, ref + ref, tmp_path / "work", name="Hello", headings=[], keywords=[],
                                wanted_font="Helvetica")
    assert out["pages"] == 1 and out["score"] < 0.51 and out["fonts"] is True and out["icons"] is None


# ---------- the choice ----------

def _row(name, *, access=True, fonts=True, icons=True, scores=(0.9, 0.9), size=100.0, installed=True):
    return {"candidate": name, "installed": installed, "access": access, "fonts": fonts, "icons": icons,
            "scores": list(scores), "size_mb": size}


def test_choose_takes_the_best_score_among_those_that_pass_the_gates():
    rows = [_row("chromium", scores=(0.95, 0.9), size=376), _row("typst", scores=(0.9, 0.9), size=14),
            _row("weasyprint", access=False, scores=(0.99, 0.99))]
    assert bench.choose(rows) == {"choice": "chromium", "fallback": "typst", "excluded": {"weasyprint": "access"}}


def test_choose_breaks_a_tie_by_the_smaller_install():
    rows = [_row("chromium", size=376), _row("typst", size=14)]
    assert bench.choose(rows)["choice"] == "typst"


def test_choose_when_none_passes_or_is_installed():
    rows = [_row("a", fonts=False), _row("b", installed=False), _row("c", icons=False)]
    assert bench.choose(rows) == {"choice": None, "fallback": None,
                                  "excluded": {"a": "fonts", "b": "not installed", "c": "icons"}}


# ---------- the table and the size ----------

def test_bench_table_has_a_row_per_candidate_and_marks_what_was_not_installed():
    rows = [{**_row("typst"), "cold": 0.4, "warm": 0.2, "french": [], "hyphens": True, "readability": [[], []]},
            {"candidate": "weasyprint", "installed": False}]
    table = bench.bench_table(rows, docs={"typst": {"Windows": "21 MB exe"}})
    lines = table.strip().splitlines()
    assert lines[0].startswith("| candidate |") and len(lines) == 4
    assert "not installed" in lines[3]
    assert "21 MB exe" in lines[2] or "21 MB exe" in table


def test_install_size_mb(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "a").write_bytes(b"x" * 1_000_000)
    (tmp_path / "b").write_bytes(b"x" * 500_000)
    assert bench.install_size_mb(tmp_path / "d") == 1.0
    assert bench.install_size_mb(tmp_path / "b") == 0.5
    assert bench.install_size_mb(tmp_path / "missing") is None


# ---------- a candidate that is not installed ----------

def test_a_missing_executable_is_recorded_not_installed(tmp_path):
    cand = bench.candidates({"WEASYPRINT": str(tmp_path / "nope"), "TYPST": str(tmp_path / "nope2")})
    names = {c.name: c for c in cand}
    assert set(names) == {"chromium", "weasyprint", "typst"}
    assert not names["weasyprint"].installed and not names["typst"].installed


def test_a_word_broken_with_a_unicode_hyphen_at_a_line_end_hyphenates():
    assert bench.hyphenates("l'interdépen‐\r\ndance")


def test_a_soft_hyphen_hyphenates_and_keeps_the_word_whole():
    text = "organisa\ufffetionnelles est considérable"  # pdfium's mark of a soft hyphen at a line end
    assert bench.hyphenates(text)
    assert bench.split_words(text) == []


def test_a_word_broken_by_a_hard_hyphen_reads_back_split():
    assert bench.split_words("l'interdépen\u2010\r\ndance des or-\nganisations") == ["interdépen‐dance", "or-ganisations"]


def test_font_names_are_read_from_the_descriptors_when_the_font_has_no_base_name():
    data = b"<< /Type /FontDescriptor /FontName /BAAAAA+Figtree-Regular /Flags 4 >>"
    assert bench.descriptor_font_names([data]) == ["BAAAAA+Figtree-Regular"]
