"""door.tailoring.style_trace: a small crop of a rendered icon traced into an SVG path (#148)."""

import re

from PIL import Image, ImageDraw

from door.tailoring import style_trace

WHITE, BLACK, CORAL = (255, 255, 255), (0, 0, 0), (230, 90, 70)


def canvas(w=100, h=100, bg=WHITE):
    image = Image.new("RGB", (w, h), bg)
    return image, ImageDraw.Draw(image)


def numbers(d):
    return [float(n) for n in re.findall(r"-?\d+\.?\d*", d)]


def test_a_disc_is_one_loop_in_points_with_the_box_of_its_ink():
    image, draw = canvas()
    draw.ellipse([20, 30, 69, 79], fill=BLACK)
    result = style_trace.trace(image, 10.0)
    assert result["bbox"] == [20, 30, 70, 80] and result["color"] == "#000000" and "fill" not in result
    assert result["viewBox"] == "0 0 5 5"
    assert result["d"].startswith("M") and result["d"].endswith("Z") and result["d"].count("M") == 1
    # in points from the ink's top left: nothing below 0 or past the box
    assert all(-0.01 <= n <= 5.01 for n in numbers(result["d"]))
    assert len(numbers(result["d"])) < 120  # simplified, not one point per pixel step


def test_a_ring_has_a_hole_as_a_second_loop():
    image, draw = canvas()
    draw.ellipse([10, 10, 89, 89], fill=BLACK)
    draw.ellipse([30, 30, 69, 69], fill=WHITE)
    assert style_trace.trace(image, 10.0)["d"].count("M") == 2


def test_a_light_glyph_on_a_coloured_ground_is_traced_by_its_difference_from_the_ground():
    image, draw = canvas(bg=CORAL)
    draw.rectangle([30, 20, 59, 79], fill=WHITE)
    result = style_trace.trace(image, 10.0)
    assert result["bbox"] == [30, 20, 60, 80] and result["viewBox"] == "0 0 3 6"
    assert result["color"] == "#ffffff"  # the strongest ink, which a picture (no known colour) is given


def test_an_image_with_no_ink_traces_to_nothing():
    image, draw = canvas()
    assert style_trace.trace(image, 10.0) is None
    draw.rectangle([40, 40, 60, 60], fill=(235, 235, 235))  # fainter than any glyph
    assert style_trace.trace(image, 10.0) is None


def test_specks_of_a_few_pixels_are_dropped():
    image, draw = canvas()
    draw.rectangle([20, 20, 59, 59], fill=BLACK)
    draw.point((80, 80), fill=BLACK)
    draw.rectangle([90, 10, 91, 11], fill=BLACK)  # 4 pixels: kept as ink
    result = style_trace.trace(image, 10.0)
    assert result["d"].count("M") == 2 and result["bbox"][2] == 92


def test_a_diagonal_edge_becomes_one_straight_segment():
    image, draw = canvas()
    draw.polygon([(10, 10), (89, 10), (89, 89)], fill=BLACK)
    result = style_trace.trace(image, 10.0)
    assert result["d"].count("L") == 2  # a triangle: three corners


def test_an_l_shape_has_six_corners():
    image, draw = canvas()
    draw.rectangle([20, 20, 39, 79], fill=BLACK)
    draw.rectangle([20, 60, 79, 79], fill=BLACK)
    result = style_trace.trace(image, 10.0)
    assert result["d"].count("L") == 5 and result["d"].count("M") == 1


def test_a_lone_speck_leaves_no_ink():
    image, draw = canvas()
    draw.point((50, 50), fill=BLACK)
    assert style_trace.trace(image, 10.0) is None
