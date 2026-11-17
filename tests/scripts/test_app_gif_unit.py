"""scripts/demo/app_gif.py: the app GIF keeps the app's colours, not only its greys."""

import importlib.util
import json

from PIL import Image, ImageDraw

from paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("app_gif", REPO_ROOT / "scripts" / "demo" / "app_gif.py")
app_gif = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app_gif)

SUCCESS = (0x3F, 0x6B, 0x4F)  # docs/design/tokens.json
ACCENT = (0x2F, 0x55, 0xC8)


def _frame(path, shade, marks):
    """A window of greys of every shade, as antialiased text has, with small coloured marks."""
    img = Image.new("RGB", (400, 250), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for x in range(400):  # with faint cool tints
        for y in range(0, 190):
            g = (x + y * 7 + shade) % 256
            d.point((x, y), fill=(g, g, min(255, g + (x + y) % 4)))
    for box, colour in marks:
        d.rectangle(box, fill=colour)
    img.save(path)


def _gif(tmp_path, marks_of):
    meta = []
    for i in range(20):
        _frame(tmp_path / f"{i}.png", 40 + i * 9, marks_of(i))
        meta.append({"file": str(tmp_path / f"{i}.png"), "at": i * 100})
    (tmp_path / "frames.json").write_text(json.dumps(meta))
    out = tmp_path / "app.gif"
    app_gif.build(tmp_path, out, width=400)
    return Image.open(out)


def _near(got, want):
    return max(abs(a - b) for a, b in zip(got, want)) <= 12


GREEN_BUTTON = ((300, 200, 340, 214), SUCCESS)
BLUE_LINK = ((20, 220, 60, 226), ACCENT)


def test_a_small_green_and_blue_survive_the_shared_palette(tmp_path):
    rgb = _gif(tmp_path, lambda i: [GREEN_BUTTON, BLUE_LINK]).convert("RGB")
    assert _near(rgb.getpixel((320, 207)), SUCCESS), rgb.getpixel((320, 207))
    assert _near(rgb.getpixel((40, 223)), ACCENT), rgb.getpixel((40, 223))


def test_a_colour_shown_in_one_frame_only_keeps_its_colour(tmp_path):
    gif = _gif(tmp_path, lambda i: [GREEN_BUTTON] if i == 7 else [])
    gif.seek(7)
    got = gif.convert("RGB").getpixel((320, 207))
    assert _near(got, SUCCESS), got
