"""Turn the app recorder's frames into docs/demo/app.gif (`npm run record:gif` in app/ runs both).

python scripts/demo/app_gif.py <frames-dir> [out.gif] [--width N]: frames.json lists each screenshot and when it was
taken; identical neighbours are merged into one longer frame, every frame is scaled to WIDTH and put on
one shared palette built from every frame's colours (a steady picture, a smaller file), and the last frame is held before the loop.
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageChops

WIDTH = 1000
HOLD_LAST_MS = 2500


def _palette(images: list[Image.Image]) -> Image.Image:
    """One palette for every frame, so colours do not flicker from frame to frame. It is built from each
    distinct colour of every frame, weighted by the square root of its count: a green shown in a few frames
    still gets its entry, and the window's many greys still get most of them. Octree, not median cut, which
    spends every entry on the greys and folds a small green or blue into one."""
    counts: Counter[tuple[int, int, int]] = Counter()
    for img in images:
        for n, colour in img.getcolors(img.width * img.height):
            counts[colour] += n
    pixels = [colour for colour, n in counts.items() for _ in range(max(1, round(math.sqrt(n))))]
    side = math.ceil(math.sqrt(len(pixels)))
    bag = Image.new("RGB", (side, side))
    bag.putdata(pixels + pixels[: side * side - len(pixels)])
    return bag.quantize(colors=255, method=Image.Quantize.FASTOCTREE)


def build(frames_dir: Path, out: Path, width: int = WIDTH) -> None:
    meta = json.loads((frames_dir / "frames.json").read_text())
    images: list[Image.Image] = []
    durations: list[int] = []
    for i, f in enumerate(meta):
        path = Path(f["file"])
        if not path.exists():
            continue
        img = Image.open(path).convert("RGB")
        if img.width != width:
            img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
        nxt = meta[i + 1]["at"] if i + 1 < len(meta) else f["at"] + HOLD_LAST_MS
        ms = max(20, nxt - f["at"])
        if images and ImageChops.difference(images[-1], img).getbbox() is None:
            durations[-1] += ms
            continue
        images.append(img)
        durations.append(ms)
    palette = _palette(images)
    frames = [img.quantize(palette=palette, dither=Image.Dither.NONE) for img in images]
    durations[-1] += HOLD_LAST_MS
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True, disposal=1)
    print(f"{out}: {len(frames)} frames, {sum(durations) / 1000:.1f} s, {out.stat().st_size // 1024} KB")  # noqa: T201


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    args = sys.argv[1:]
    width = WIDTH
    if "--width" in args:
        i = args.index("--width")
        width = int(args[i + 1])
        del args[i:i + 2]
    build(Path(args[0]), Path(args[1]) if len(args) > 1 else root / "docs" / "demo" / "app.gif", width)
