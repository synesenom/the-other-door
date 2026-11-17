"""scripts/demo/app_gif.py: the app GIF keeps the app's colours, not only its greys."""

import importlib.util
import json

from PIL import Image, ImageDraw

from paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("app_gif", REPO_ROOT / "scripts" / "demo" / "app_gif.py")
app_gif = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app_gif)

GREEN = (46, 125, 50)
BLUE = (37, 99, 235)


def _frame(path, shade):
    """A window of greys of every shade, as antialiased text has, with a small green button and a blue link."""
    img = Image.new("RGB", (400, 250), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for x in range(400):  # with faint cool tints
        for y in range(0, 190):
            g = (x + y * 7 + shade) % 256
            d.point((x, y), fill=(g, g, min(255, g + (x + y) % 4)))
    d.rectangle((300, 200, 340, 214), fill=GREEN)
    d.rectangle((20, 220, 60, 226), fill=BLUE)
    img.save(path)


def test_a_small_green_and_blue_survive_the_shared_palette(tmp_path):
    meta = []
    for i in range(6):
        _frame(tmp_path / f"{i}.png", 40 + i * 20)
        meta.append({"file": str(tmp_path / f"{i}.png"), "at": i * 100})
    (tmp_path / "frames.json").write_text(json.dumps(meta))
    out = tmp_path / "app.gif"

    app_gif.build(tmp_path, out, width=400)

    rgb = Image.open(out).convert("RGB")
    for xy, want in (((320, 207), GREEN), ((40, 223), BLUE)):
        got = rgb.getpixel(xy)
        assert max(abs(a - b) for a, b in zip(got, want)) <= 12, (want, got)
