"""scripts/cv_style_proto.py: the pure parts of the CV style builder prototype (#154)."""

import importlib.util
import json
import re

import pytest

from PIL import Image

from paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("cv_style_proto", REPO_ROOT / "scripts" / "cv_style_proto.py")
proto = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(proto)

# a one-page PDF written by hand: a red rectangle and a line of blue 14 pt Helvetica
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


# glyph by glyph, as Chromium writes a page: "Hel" + "lo" abut and make one run, "far" does not join them
_GLYPHS = _PDF.replace(b"BT /F1 14 Tf 20 150 Td (Hello World) Tj ET",
                       b"BT /F1 14 Tf 20 150 Td (Hel) Tj ET BT /F1 14 Tf 41 150 Td (lo) Tj ET BT /F1 14 Tf 120 150 Td (far) Tj ET"
                       ).replace(b"/Length 110", b"/Length 200")


def test_glyphs_written_one_by_one_are_read_back_as_runs(tmp_path):
    pdf = tmp_path / "g.pdf"
    pdf.write_bytes(_GLYPHS)
    texts = proto.extract_style(pdf)["pages"][0]["texts"]
    assert [t["text"] for t in texts] == ["Hello", "far"]


def test_the_html_is_taken_from_the_models_reply():
    reply = "I see two columns.\n```html\n<!doctype html><p>a</p>\n```\nDone."
    assert proto.extract_html(reply) == "<!doctype html><p>a</p>"
    assert proto.extract_html("no code here") is None
    assert proto.extract_html("```html\n<p>cut off") is None


def _text(text, size=12, color=(0, 0, 0), bbox=(10, 10, 80, 22)):
    return {"text": text, "size": size, "color": color, "bbox": list(bbox), "font": "X"}


def test_style_extraction_reads_text_runs_and_shapes(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(_PDF)
    page = proto.extract_style(pdf)["pages"][0]
    assert page["size"] == [200, 200]
    run = page["texts"][0]
    assert run["text"] == "Hello World" and round(run["size"]) == 14
    assert tuple(run["color"]) == (0, 0, 255) and "Helvetica" in run["font"]
    # origin top left, like the page image: the text sits near the top, the rectangle near the bottom
    assert run["bbox"][1] < 60 and page["shapes"][0]["bbox"][1] > 160
    shape = page["shapes"][0]
    assert tuple(shape["fill"]) == (255, 0, 0) and shape["d"].startswith("M")


def test_elements_are_paired_by_text_with_their_differences():
    original = [_text("Alice", 20, (0, 0, 0)), _text("Skills", 12), _text("only here")]
    rebuilt = [_text("alice ", 18, (10, 0, 0), (12, 10, 80, 22)), _text("Skills", 12), _text("extra")]
    result = proto.match_elements(original, rebuilt)
    assert [p["text"] for p in result["pairs"]] == ["Alice", "Skills"]
    assert result["pairs"][0]["d_size"] == -2 and result["pairs"][0]["d_x"] == 2
    assert result["pairs"][1]["d_size"] == 0
    assert result["missing"] == ["only here"] and result["extra"] == ["extra"]


def test_blurred_score_ranks_a_shift_above_a_different_page():
    white = Image.new("RGB", (100, 100), "white")
    black = Image.new("RGB", (100, 100), "black")
    bar = white.copy()
    bar.paste(Image.new("RGB", (20, 60), "black"), (20, 20))
    shifted = white.copy()
    shifted.paste(Image.new("RGB", (20, 60), "black"), (21, 20))
    assert proto.blurred_score(bar, bar) == 1.0
    assert proto.blurred_score(white, black) < 0.05
    assert proto.blurred_score(bar, shifted) > proto.blurred_score(bar, white)


def test_a_run_split_differently_still_pairs_with_the_run_that_contains_it():
    result = proto.match_elements([_text("Bluebird Systems"), _text("2023 - present")],
                                  [_text("Bluebird"), _text("Systems 2023 - present")])
    assert result["missing"] == [] and result["extra"] == []


def test_a_blank_page_scores_near_zero_even_when_the_original_is_mostly_white():
    page = Image.new("RGB", (200, 200), "white")
    page.paste(Image.new("RGB", (100, 6), "black"), (20, 20))  # a little ink on white
    assert proto.blurred_score(page, Image.new("RGB", (200, 200), "white")) < 0.1


def test_feedback_names_what_to_fix():
    result = proto.match_elements([_text("Skills", 14), _text("gone")], [_text("Skills", 10)])
    text = proto.feedback_text(result, 0.8)
    assert "0.80" in text and "Skills" in text and "gone" in text


def test_side_by_side_is_as_wide_as_its_parts_and_as_tall_as_the_tallest():
    a, b = Image.new("RGB", (100, 150), "red"), Image.new("RGB", (120, 90), "blue")
    sheet = proto.side_by_side([a, b], gap=10)
    assert sheet.size == (230, 150)


def test_stress_variants_leave_the_original_alone():
    record = proto.cvs.record(1)
    before = repr(record)
    variants = proto.stress_variants(record)
    assert set(variants) == {"short", "long", "extra_section", "french"}
    assert repr(record) == before
    assert len(variants["short"]["experience"]) < len(record["experience"])
    assert len(variants["long"]["experience"]) > len(record["experience"])
    assert len(variants["extra_section"]["extra_sections"]) == 1
    assert variants["french"]["summary"] != record["summary"]


def test_cost_is_read_from_the_envelope_and_missing_is_zero():
    assert proto.cost_of('{"total_cost_usd": 0.42}') == 0.42
    assert proto.cost_of('{"result": "x"}') == 0.0
    assert proto.cost_of("not json") == 0.0


def _row(rounds=3, minutes=5.0, cost=1.0, recognisable=True, stress=True):
    return proto.record_row("cv", rounds=rounds, minutes=minutes, cost=cost, score=0.9,
                            recognisable=recognisable, stress_holds=stress)


def test_verdict_is_go_when_every_threshold_is_met():
    rows = [_row() for _ in range(8)]
    assert proto.verdict(rows)["go"] is True


def test_verdict_names_each_threshold_it_misses():
    rows = [_row(recognisable=i < 4, rounds=6, minutes=11, cost=3.0, stress=False) for i in range(8)]
    result = proto.verdict(rows)
    assert result["go"] is False
    assert len(result["failed"]) == 5


def test_markdown_table_has_a_row_per_cv():
    table = proto.markdown_table([_row(), _row()])
    assert len(table.strip().splitlines()) == 4


def test_the_eight_made_up_cvs_use_example_addresses_only():
    for n in range(1, 9):
        email = proto.cvs.record(n)["contact"]["email"]
        assert re.fullmatch(r"[\w.]+@example\.com", email)


def test_the_default_look_fills_the_templates_macros():
    tex = proto.cvs.to_default_tex(proto.cvs.record(1))
    assert "\\cvheader{" in tex and "\\workexperience{" in tex and "<<fonts>>" not in tex


def test_a_given_pdf_is_rebuilt_as_its_own_cv_named_after_the_file(tmp_path, monkeypatch):
    pdf = tmp_path / "scrubbed-altacv-icons-fr.pdf"
    pdf.write_bytes(_PDF)
    monkeypatch.setenv("DOOR_HOME", str(tmp_path / "home"))
    seen = []
    monkeypatch.setattr(proto, "run_pdf", lambda path, with_stress: seen.append((path, with_stress)) or {"cv": path.stem})
    monkeypatch.setattr(proto, "OUT", tmp_path / "out")
    proto.main(["--pdf", str(pdf), "--stress"])
    assert seen == [(pdf, True)]
    assert proto.pdf_work_dir(pdf) == tmp_path / "out" / "pdf-scrubbed-altacv-icons-fr"


def test_a_range_of_cvs_is_every_number_in_it():
    assert proto.parse_cvs("3") == [3]
    assert proto.parse_cvs("2-4") == [2, 3, 4]


def test_recognisable_is_judged_against_the_rows_given_not_a_fixed_eight():
    nine = lambda yes: [_row(recognisable=i < yes) for i in range(9)]  # noqa: E731
    assert proto.verdict(nine(5))["go"] is False  # 5 of 9 is under 5 in 8
    assert proto.verdict(nine(6))["go"] is True


def _record(folder, design, cost, stress_cost):
    folder.mkdir(parents=True)
    (folder / "record.json").write_text(json.dumps({
        "design": design, "rounds": 3, "minutes": 1.0, "cost": cost, "score": 0.9,
        "stress": {"holds": True, "cost": stress_cost}}))


def test_the_report_has_every_record_and_an_unjudged_design_is_not_recognisable(tmp_path, monkeypatch):
    monkeypatch.setattr(proto, "OUT", tmp_path)
    _record(tmp_path / "cv1-made-up", "made-up", 1.0, 0.5)
    _record(tmp_path / "pdf-real", "pdf-real", 1.5, 0.9)
    (tmp_path / "judgement.json").write_text(json.dumps({"made-up": True}))
    lines = proto.report().splitlines()
    assert any(line.startswith("| made-up |") and "| yes |" in line for line in lines)
    real = next(line for line in lines if line.startswith("| pdf-real |"))
    assert "| 1.5 |" in real and "| no |" in real  # the build's cost, not the stress renders'


def test_the_cost_judged_is_the_builds_and_the_stress_renders_cost_apart(tmp_path, monkeypatch):
    for name in ("original_page_1.png", "render_page_1.png"):
        Image.new("RGB", (10, 10), "white").save(tmp_path / name)
    (tmp_path / "best.html").write_text("<p>x</p>")
    monkeypatch.setattr(proto, "rebuild", lambda work, original: {"rounds": 2, "cost": 1.2})
    monkeypatch.setattr(proto, "stress", lambda n, work, html, pages: {"holds": True, "cost": 0.8})
    monkeypatch.setattr(proto, "pages_of", lambda pdf: 1)
    summary = proto.finish(tmp_path, tmp_path / "original.pdf", {"design": "d"}, 1, True, [])
    assert summary["cost"] == 1.2 and summary["stress"]["cost"] == 0.8


def test_a_live_run_refuses_to_log_into_the_real_data_folder(monkeypatch):
    monkeypatch.delenv("DOOR_HOME", raising=False)
    monkeypatch.setattr(proto, "run_cv", lambda n, s: pytest.fail("ran without DOOR_HOME"))
    with pytest.raises(SystemExit, match="DOOR_HOME"):
        proto.main(["--cv", "1"])
