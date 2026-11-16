"""Comparing a rebuild's render with the original CV (#204): both are `style_extract.extract` results, so the pieces
are tested on small made-up dicts, the blurred score on synthetic images, the two PDF ends on the style corpus."""

import pytest
from PIL import Image, ImageDraw

from door.tailoring import pdf_render, style_compare, style_extract
from paths import TESTS_DIR

STYLES = TESTS_DIR / "tailoring" / "fixtures" / "styles"


def run(text, x=50.0, y=100.0, size=10.0, color="#000000", icon=False):
    return {"text": text, "bbox": [x, y, x + 5 * len(text), y + size], "size": size, "color": color, "icon": icon}


def icon(x, y, near=None, size=9.0, color="#ffffff"):
    return {"bbox": [x, y, x + size, y + size], "color": color, "near": {"text": near, "side": "right"} if near else None}


def style(runs, icons=()):
    return {"runs": list(runs), "icons": list(icons)}


def test_identical_styles_have_no_differences():
    s = style([run("Jane Doe", size=24), run("Experience", y=200)], [icon(10, 10, "Jane Doe")])
    diffs = style_compare.match(s, s)
    assert diffs["missing"] == [] and diffs["extra"] == []
    assert style_compare.worst_offset_pt(diffs) == 0.0
    assert all(p["dx"] == p["dy"] == p["d_size"] == p["d_color"] == 0 for p in diffs["runs"])


def test_a_shifted_larger_run_of_another_colour_is_measured():
    original = style([run("Experience", x=50, y=100, size=10, color="#000000")])
    render = style([run("experience", x=53, y=98, size=12, color="#336699")])
    (pair,) = style_compare.match(original, render)["runs"]
    assert (pair["dx"], pair["dy"], pair["d_size"]) == (3.0, -2.0, 2.0)
    assert pair["d_color"] == 0x99
    assert pair["color"] == "#000000" and pair["render_color"] == "#336699"


def test_the_nearest_run_with_the_same_text_is_the_partner():
    original = style([run("2021", x=50, y=100), run("2021", x=50, y=300)])
    render = style([run("2021", x=50, y=301), run("2021", x=50, y=101)])
    pairs = style_compare.match(original, render)["runs"]
    assert [(p["dy"]) for p in pairs] == [1.0, 1.0]


def test_runs_with_no_partner_are_missing_or_extra():
    diffs = style_compare.match(style([run("Alpha"), run("Beta", y=130)]), style([run("Alpha"), run("Gamma", y=160)]))
    assert diffs["missing"] == ["Beta"] and diffs["extra"] == ["Gamma"]


def test_a_run_the_render_split_or_joined_is_paired_without_an_offset():
    diffs = style_compare.match(style([run("Senior Controller")]), style([run("Senior Controller | Acme", x=90)]))
    assert diffs["missing"] == [] and diffs["extra"] == []
    assert diffs["runs"][0]["split"] is True
    assert style_compare.worst_offset_pt(diffs) == 0.0


def test_icon_font_runs_are_not_text():
    diffs = style_compare.match(style([run("", icon=True), run("Hi")]), style([run("Hi")]))
    assert diffs["missing"] == [] and diffs["extra"] == []


def test_icons_are_paired_by_their_text_then_by_position():
    original = style([], [icon(10, 10, "a@b.c"), icon(10, 40, "+45 1")])
    render = style([], [icon(12, 44, "+45 1", size=11, color="#cccccc"), icon(10, 10, "a@b.c")])
    first, second = style_compare.match(original, render)["icons"]
    assert (first["dx"], first["dy"]) == (0.0, 0.0)
    assert (second["dx"], second["dy"], second["d_size"]) == (2.0, 4.0, 2.0)
    assert second["d_color"] == 0x33


def test_an_icon_with_no_text_is_paired_with_the_nearest_unused_one_and_the_rest_counted():
    diffs = style_compare.match(style([], [icon(10, 10), icon(200, 10)]), style([], [icon(11, 10)]))
    assert len(diffs["icons"]) == 1 and diffs["icons"][0]["dx"] == 1.0
    assert diffs["icons_missing"] == 1 and diffs["icons_extra"] == 0


def test_the_worst_offset_is_the_largest_shift_of_a_text_or_an_icon():
    diffs = style_compare.match(style([run("A", x=50), run("B", x=50, y=300)], [icon(10, 10, "A")]),
                                style([run("A", x=51), run("B", x=50, y=307)], [icon(10, 14, "A")]))
    assert style_compare.worst_offset_pt(diffs) == 7.0


def test_nothing_matched_of_a_nonempty_original_is_not_within_any_offset():
    assert style_compare.worst_offset_pt(style_compare.match(style([run("A")]), style([]))) == float("inf")
    assert style_compare.worst_offset_pt(style_compare.match(style([]), style([]))) == 0.0


def test_feedback_names_the_worst_offenders_first_and_what_is_missing():
    original = style([run(f"line {i}", y=100 + 20 * i) for i in range(30)] + [run("Gone", y=900)])
    render = style([run(f"line {i}", y=100 + 20 * i + (i if i < 20 else 0)) for i in range(30)])
    text = style_compare.feedback(style_compare.match(original, render), score=0.8765)
    lines = text.splitlines()
    assert "0.88" in lines[0]
    assert "line 19" in lines[1]
    assert len([ln for ln in lines if ln.startswith("- ")]) <= 12
    assert "Gone" in text


def test_feedback_of_a_perfect_render_is_the_score_alone():
    s = style([run("A")])
    assert style_compare.feedback(style_compare.match(s, s), score=1.0).count("\n") == 0


# ---------- the blurred image score ----------

def page(boxes, size=(200, 280)):
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for box in boxes:
        draw.rectangle(box, fill="black")
    return image


def test_the_same_image_scores_one_and_a_blank_page_scores_zero():
    a = page([(20, 20, 120, 40), (20, 80, 60, 200)])
    assert style_compare.blurred_score(a, a) == pytest.approx(1.0)
    assert style_compare.blurred_score(a, page([])) == pytest.approx(0.0, abs=0.02)


def test_a_small_shift_scores_better_than_a_large_one():
    a = page([(20, 20, 120, 40)])
    near = style_compare.blurred_score(a, page([(22, 20, 122, 40)]))
    far = style_compare.blurred_score(a, page([(20, 120, 120, 140)]))
    assert 1.0 > near > far


def test_images_of_other_sizes_are_compared_on_their_common_part():
    assert style_compare.blurred_score(page([(20, 20, 60, 40)]), page([(20, 20, 60, 40)], size=(200, 300))) == pytest.approx(1.0)


def test_pages_score_averages_the_pages_and_a_missing_page_counts_zero():
    a, b = page([(20, 20, 120, 40)]), page([(20, 80, 60, 200)])
    assert style_compare.pages_score([a, b], [a, b]) == pytest.approx(1.0)
    assert style_compare.pages_score([a, b], [a]) == pytest.approx(0.5)
    assert style_compare.pages_score([a], [a, b]) == pytest.approx(0.5)
    assert style_compare.pages_score([], []) == 1.0


# ---------- when to stop ----------

def test_it_goes_on_while_the_rounds_gain_and_the_offsets_are_large():
    assert not style_compare.should_stop([0.6], 12.0)
    assert not style_compare.should_stop([0.6, 0.7], 5.0)


def test_it_stops_when_every_matched_element_is_within_two_points():
    assert style_compare.should_stop([0.6], 2.0)
    assert not style_compare.should_stop([0.6], 2.1)


def test_it_stops_when_the_last_round_gained_under_half_a_percent_over_the_best_before():
    assert style_compare.should_stop([0.80, 0.90, 0.903], 9.0)
    assert style_compare.should_stop([0.80, 0.90, 0.85], 9.0)
    assert not style_compare.should_stop([0.80, 0.90, 0.906], 9.0)


def test_it_stops_at_the_cap_whatever_the_gain():
    scores = [0.1 * i for i in range(1, 8)]
    assert style_compare.should_stop(scores, 50.0)
    assert not style_compare.should_stop(scores[:6], 50.0)
    assert style_compare.should_stop(scores[:3], 50.0, cap=3)


def test_the_best_round_is_the_first_of_the_highest_scores():
    assert style_compare.best_round([0.5, 0.9, 0.8, 0.9]) == 1
    assert style_compare.best_round([0.7]) == 0
    with pytest.raises(ValueError):
        style_compare.best_round([])


# ---------- the corpus end to end ----------

@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    out = {}
    for stem in ("latex-classic", "html-word-two-column"):
        pdf = STYLES / f"{stem}.pdf"
        folder = tmp_path_factory.mktemp(stem)
        out[stem] = (style_extract.extract(pdf), style_compare.page_images(pdf, folder))
    return out


def test_a_cv_compared_with_itself_scores_one_with_no_offset(corpus):
    extracted, images = corpus["latex-classic"]
    diffs = style_compare.match(extracted, extracted)
    assert diffs["missing"] == [] and diffs["extra"] == []
    assert style_compare.worst_offset_pt(diffs) == 0.0
    assert style_compare.pages_score(images, images) == pytest.approx(1.0)


def test_two_different_cvs_score_lower_and_differ(corpus):
    (a, a_images), (b, b_images) = corpus["latex-classic"], corpus["html-word-two-column"]
    assert style_compare.pages_score(a_images, b_images) < 0.9
    diffs = style_compare.match(a, b)
    assert diffs["missing"] and style_compare.should_stop([0.5], style_compare.worst_offset_pt(diffs)) is False
