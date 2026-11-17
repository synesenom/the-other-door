"""Comparing a rebuild's render with the original CV (#204): both are `style_extract.extract` results, so the pieces
are tested on small made-up dicts, the blurred score on synthetic images, the two PDF ends on the style corpus."""

import pytest
from PIL import Image, ImageDraw

from door.tailoring import pdf_render, style_compare, style_extract
from paths import TESTS_DIR

STYLES = TESTS_DIR / "tailoring" / "fixtures" / "styles"


def run(text, x=50.0, y=100.0, size=10.0, color="#000000", icon=False, page=1):
    return {"text": text, "bbox": [x, y, x + 5 * len(text), y + size], "size": size, "color": color, "icon": icon, "page": page}


def icon(x, y, near=None, size=9.0, color="#ffffff", page=1):
    return {"bbox": [x, y, x + size, y + size], "color": color, "near": {"text": near, "side": "right"} if near else None,
            "page": page}


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
    assert style_compare.worst_offset_pt(diffs) == 40.0  # its own shift, not none: round one is not "within"
    assert not style_compare.should_stop([0.5], style_compare.worst_offset_pt(diffs))


def test_a_line_the_render_cut_in_two_pairs_both_parts_and_a_joined_render_holds_both_originals():
    cut = style_compare.match(style([run("Senior Controller Acme", y=100)]),
                              style([run("Senior Controller", y=102), run("Acme", y=102, x=150)]))
    assert cut["missing"] == [] and cut["extra"] == ["Acme"]  # "Acme" is under the minimum length: not a part
    cut = style_compare.match(style([run("Senior Controller | Acme Corp", y=100)]),
                              style([run("Senior Controller", y=102), run("| Acme Corp", y=102, x=150)]))
    assert cut["missing"] == [] and cut["extra"] == [] and cut["runs"][0]["dy"] == 2.0
    joined = style_compare.match(style([run("First line here", y=100), run("Second line here", y=120)]),
                                 style([run("First line here Second line here", y=100)]))
    assert joined["missing"] == [] and joined["extra"] == [] and len(joined["runs"]) == 2


def test_a_short_text_is_not_paired_by_being_part_of_another():
    diffs = style_compare.match(style([run("2019"), run("|", y=120), run("IT", y=140)]),
                                style([run("Controller 2019 | IT Aarhus", y=300)]))
    assert diffs["runs"] == [] and diffs["missing"] == ["2019", "|", "IT"]


def test_only_split_pairs_do_not_stop_the_loop_in_round_one():
    diffs = style_compare.match(style([run("Senior Controller", y=100)]), style([run("Senior Controller | Acme", y=160)]))
    assert style_compare.worst_offset_pt(diffs) == 60.0


def test_alike_runs_take_their_own_nearest_partner_not_the_first_one_in_order():
    original = style([run("Python", y=200), run("Python", y=100)])
    render = style([run("Python", y=140), run("Python", y=400)])
    diffs = style_compare.match(original, render)
    assert style_compare.worst_offset_pt(diffs) == 200.0  # 100 takes 140 (40 away), 200 gets 400; in order it was 300


def test_alike_icons_take_their_own_nearest_partner_too():
    diffs = style_compare.match(style([], [icon(10, 200), icon(10, 100)]), style([], [icon(10, 140), icon(10, 400)]))
    assert style_compare.worst_offset_pt(diffs) == 200.0


def test_a_run_is_paired_on_its_own_page_first():
    original = style([run("Python", y=100, page=1), run("Python", y=100, page=2)])
    render = style([run("Python", y=100, page=2), run("Python", y=103, page=1)])
    diffs = style_compare.match(original, render)
    assert sorted(p["dy"] for p in diffs["runs"]) == [0.0, 3.0]
    assert style_compare.worst_offset_pt(diffs) == 3.0


def test_a_pair_across_pages_is_off_by_any_distance_and_the_feedback_says_so():
    diffs = style_compare.match(style([run("Experience", page=2)]), style([run("Experience", page=1)]))
    assert style_compare.worst_offset_pt(diffs) == float("inf")
    assert "on page 1, original page 2" in style_compare.feedback(diffs, 0.9)
    icons = style_compare.match(style([], [icon(10, 10, "a@b.c", page=2)]), style([], [icon(10, 10, "a@b.c", page=1)]))
    assert style_compare.worst_offset_pt(icons) == float("inf")
    assert "icon beside 'a@b.c': on page 1, original page 2" in style_compare.feedback(icons, 0.9)


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


def test_feedback_names_a_page_count_unlike_the_originals_first():
    """Every line after a page break shifts with it, so the overflow is the first thing to fix (#244)."""
    original = {**style([run("A"), run("B", page=2)]), "page_count": 2}
    longer = {**style([run("A", y=140), run("B", page=2)]), "page_count": 3}
    lines = style_compare.feedback(style_compare.match(original, longer), score=0.4).splitlines()
    assert "3 pages" in lines[1] and "2" in lines[1]
    shorter = {**style([run("A"), run("B", y=120)]), "page_count": 1}
    assert "1 page" in style_compare.feedback(style_compare.match(original, shorter), score=0.4).splitlines()[1]
    same = style_compare.feedback(style_compare.match(original, {**original}), score=1.0)
    assert "pages" not in same
    unknown = style_compare.match(style([run("A")]), longer)  # an original with no page count says nothing of pages
    assert unknown["pages"] == (None, 3) and "page" not in style_compare.feedback(unknown, score=0.4).splitlines()[1]


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


def score(a, b):
    """`pages_score` of one page each."""
    return style_compare.pages_score([a], [b])


def test_the_same_image_scores_one_and_a_blank_page_scores_zero():
    a = page([(20, 20, 120, 40), (20, 80, 60, 200)])
    assert score(a, a) == pytest.approx(1.0)
    assert score(a, page([])) == pytest.approx(0.0, abs=0.02)


def test_a_rebuild_with_more_ink_than_the_original_does_not_floor_at_zero():
    a = page([(20, 20, 60, 40)])
    full = page([(0, 0, 200, 280)])
    wrong = page([(20, 20, 120, 200)])
    assert score(a, wrong) > 0.0
    assert score(a, wrong) < score(a, page([(22, 20, 62, 40)]))
    assert score(a, full) >= 0.0


def test_a_small_shift_scores_better_than_a_large_one():
    a = page([(20, 20, 120, 40)])
    near = score(a, page([(22, 20, 122, 40)]))
    far = score(a, page([(20, 120, 120, 140)]))  # 100 pixels down: beyond the vertical reach of a 280-pixel page
    assert 1.0 > near > far


def test_images_of_other_sizes_are_compared_on_their_common_part():
    assert score(page([(20, 20, 60, 40)]), page([(20, 20, 60, 40)], size=(200, 300))) == pytest.approx(1.0)
    assert score(page([(20, 20, 60, 40)], size=(240, 280)), page([(20, 20, 60, 40)])) == pytest.approx(1.0)


def lines(count, top=20, step=20, size=(200, 280)):
    """A page of `count` text-like lines from `top`, `step` pixels apart."""
    return page([(20, top + step * i, 100 - 10 * (i % 3), top + step * i + 8) for i in range(count)], size)


def test_pages_score_of_the_same_pages_is_one_and_of_blank_pages_zero():
    a, b = page([(20, 20, 120, 40)]), page([(20, 80, 60, 200)])
    assert style_compare.pages_score([a, b], [a, b]) == pytest.approx(1.0)
    assert style_compare.pages_score([a, b], [page([]), page([])]) == pytest.approx(0.0, abs=0.02)
    assert style_compare.pages_score([], []) == 1.0


def test_a_page_only_one_side_has_costs_what_it_holds_not_a_whole_page():
    a, b = lines(12), lines(12)
    one_line = lines(1)
    assert style_compare.pages_score([a, b], [a, b, one_line]) > 0.9
    assert style_compare.pages_score([a, b], [a]) < style_compare.pages_score([a, b], [a, b, one_line])
    assert style_compare.pages_score([a, b], [a]) < 0.7


def test_a_rebuild_a_few_lines_too_long_scores_close_to_the_original():
    """The same lines, each page's shifted down by two lines, the last two of each page flowing onto the next (#244)."""
    original = [lines(12), lines(12)]
    render = [lines(12, top=60), lines(12, top=20), lines(2)]  # page 2 starts with page 1's last two lines
    assert style_compare.pages_score(original, render) > 0.75


def test_a_rebuild_far_too_long_scores_low():
    """Three times the original's pages, each with a few lines: not a few lines over, so each extra page costs a whole
    one. It stays far below a good rebuild (the loop's small-gain stop does not end it, it goes on) and below the 0.55
    a build needs to be kept (#241)."""
    original = [lines(12), lines(12)]
    render = [lines(4), lines(4)] + [lines(4)] * 4
    score = style_compare.pages_score(original, render)
    assert score < 0.3 < style_compare.GOOD
    assert not style_compare.should_stop([score, score], 9.0)


def test_an_original_page_taller_than_the_renders_is_compared_with_white_below_not_black():
    tall = lines(12, size=(200, 400))
    assert style_compare.pages_score([tall], [lines(12)]) > 0.9


def test_a_shift_does_not_make_another_layout_look_alike():
    original = [lines(12), lines(12)]
    side = page([(110, 20 + 20 * i, 180, 28 + 20 * i) for i in range(12)])  # the same lines in another column
    assert style_compare.pages_score(original, [side, side]) < 0.3


# ---------- when to stop ----------

def test_it_goes_on_while_the_rounds_gain_and_the_offsets_are_large():
    assert not style_compare.should_stop([0.6], 12.0)
    assert not style_compare.should_stop([0.6, 0.7], 5.0)


def test_it_stops_when_every_matched_element_is_within_two_points():
    assert style_compare.should_stop([0.6], 2.0)
    assert not style_compare.should_stop([0.6], 2.1)


def test_it_stops_when_the_last_round_gained_under_a_quarter_percent_over_the_best_before():
    assert style_compare.should_stop([0.80, 0.90, 0.902], 9.0)
    assert style_compare.should_stop([0.80, 0.90, 0.85], 9.0)
    assert not style_compare.should_stop([0.80, 0.90, 0.904], 9.0)


def test_a_small_gain_does_not_stop_a_build_whose_best_score_is_still_low():
    assert not style_compare.should_stop([0.0, 0.0], 9.0)
    assert not style_compare.should_stop([0.10, 0.10], 9.0)
    assert style_compare.should_stop([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 9.0)


@pytest.mark.parametrize("scores", [
    [0.486, 0.486],  # html-canva-icons (#243): flat, its columns swapped
    [0.306, 0.007],  # latex-sidebar with a long CV: a worse round after a poor first draft (scores 0.985 when it goes well)
    [0.375, 0.389, 0.234],  # scrubbed-pages-header-en
    [0.501, 0.754, 0.463],  # latex-classic: good, not yet as good as a rebuild that goes well
])
def test_a_flat_or_worse_round_does_not_stop_a_build_whose_best_is_below_a_good_rebuild(scores):
    assert max(scores) < style_compare.GOOD
    assert not style_compare.should_stop(scores, 9.0)


def test_once_the_best_is_a_good_rebuild_a_flat_or_worse_round_stops_it():
    assert style_compare.should_stop([0.539, 0.724, 0.91, 0.502], 9.0)  # html-word-two-column
    assert style_compare.should_stop([0.92, 0.985, 0.985], 9.0)  # latex-sidebar
    assert style_compare.should_stop([style_compare.GOOD, style_compare.GOOD], 9.0)  # a best exactly at GOOD is good


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


def test_the_original_run_onto_one_more_page_still_scores_high(tmp_path):
    """A real CV (two pages) printed a few lines too long: its second page shifted down, its last lines on a third (#244)."""
    images = style_compare.page_images(STYLES / "scrubbed-pages-header-en.pdf", tmp_path)
    width, height = images[1].size
    shift = height // 12
    second = Image.new("RGB", (width, height), "white")
    second.paste(images[1].crop((0, 0, width, height - shift)), (0, shift))
    third = Image.new("RGB", (width, height), "white")
    third.paste(images[1].crop((0, height - shift, width, height)), (0, 0))
    assert style_compare.pages_score(images, [images[0], second, third]) > 0.8


def test_a_compatibility_form_in_one_render_pairs_with_its_plain_letters_in_the_other():
    original = style([run("Skills 2021", x=50, y=100)])
    render = style([run("Ｓｋｉｌｌｓ 2021", x=50, y=103)])  # full-width letters, as some PDFs encode them
    result = style_compare.match(original, render)
    assert [p["dy"] for p in result["runs"]] == [3.0]
