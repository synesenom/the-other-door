"""Compare a rebuilt CV's render with the original (#204, epic #144): pure and offline, Pillow only.

Both sides are `style_extract.extract` results (`runs` and `icons`, points, origin top left). `match` pairs the text
runs by their normalised text (the nearest run of the same text when there are several) and the icons by the text
they sit beside, then by position, and says how each pair differs: `dx`, `dy` (the render's box minus the original's),
`d_size`, and `d_color` (`style_trace.distance`, the largest channel difference). `blurred_score` and `pages_score`
say how alike the page images look, `feedback` is what the next round tells the model, and `should_stop` /
`best_round` are the loop's stopping rule: stop at `CAP` rounds, when every matched element is within `WITHIN_PT`
points, or when the last round gained under `MIN_GAIN` over the best before it; the best round is kept.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

from door.tailoring import pdf_render, style_trace

CAP = 7  # rounds
WITHIN_PT = 2.0  # every matched element this close: nothing left to fix
MIN_GAIN = 0.005  # a round that adds less than this over the best before it is not worth another
BLUR_RADIUS = 4.0  # pixels at the render's 150 dpi
_FEEDBACK_LIMIT = 12
# a difference smaller than these is not worth telling the model about
_OFF_SIZE, _OFF_COLOR, _OFF_SHIFT = 0.5, 40, 6.0


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _centre(icon: dict) -> tuple[float, float]:
    b = icon["bbox"]
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _extent(icon: dict) -> float:
    b = icon["bbox"]
    return max(b[2] - b[0], b[3] - b[1])


def _run_pair(a: dict, b: dict) -> dict:
    return {"text": a["text"], "dx": round(b["bbox"][0] - a["bbox"][0], 1), "dy": round(b["bbox"][1] - a["bbox"][1], 1),
            "d_size": round(b["size"] - a["size"], 1),
            "d_color": style_trace.distance(style_trace.channels(a["color"]), style_trace.channels(b["color"])),
            "color": a["color"], "render_color": b["color"]}


def _text_pairs(original: list[dict], render: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    pool: dict[str, list[dict]] = {}
    for run in render:
        pool.setdefault(_norm(run["text"]), []).append(run)
    pairs, missing = [], []
    for run in original:
        candidates = pool.get(_norm(run["text"]))
        if not candidates:
            missing.append(run)
            continue
        other = min(candidates, key=lambda c: abs(c["bbox"][0] - run["bbox"][0]) + abs(c["bbox"][1] - run["bbox"][1]))
        candidates.remove(other)
        pairs.append(_run_pair(run, other))
    rest = [r for runs in pool.values() for r in runs]
    still_missing = []
    for run in missing:  # a run the render split or joined differently: pair it with an unused one that holds it or is held by it
        key = _norm(run["text"])
        hit = next((r for r in rest if key in _norm(r["text"]) or _norm(r["text"]) in key), None)
        if hit is None:
            still_missing.append(run["text"])
            continue
        rest.remove(hit)
        pairs.append({"text": run["text"], "dx": 0.0, "dy": 0.0, "d_size": 0.0, "d_color": 0, "split": True,
                      "color": run["color"], "render_color": hit["color"]})
    return pairs, still_missing, [r["text"] for r in rest]


def _icon_pair(a: dict, b: dict) -> dict:
    return {"near": (a.get("near") or {}).get("text"), "dx": round(b["bbox"][0] - a["bbox"][0], 1),
            "dy": round(b["bbox"][1] - a["bbox"][1], 1), "d_size": round(_extent(b) - _extent(a), 1),
            "d_color": style_trace.distance(style_trace.channels(a["color"]), style_trace.channels(b["color"])),
            "color": a["color"], "render_color": b["color"]}


def _icon_pairs(original: list[dict], render: list[dict]) -> tuple[list[dict], int, int]:
    unused = list(render)

    def far(a, b):
        (ax, ay), (bx, by) = _centre(a), _centre(b)
        return math.hypot(ax - bx, ay - by)

    pairs, unpaired = [], []
    for icon in original:  # beside the same text first
        key = _norm((icon.get("near") or {}).get("text") or "")
        same = [c for c in unused if key and _norm((c.get("near") or {}).get("text") or "") == key]
        if same:
            other = min(same, key=lambda c: far(icon, c))
            unused.remove(other)
            pairs.append(_icon_pair(icon, other))
        else:
            unpaired.append(icon)
    for icon in unpaired:  # then the nearest one left
        if not unused:
            break
        other = min(unused, key=lambda c: far(icon, c))
        unused.remove(other)
        pairs.append(_icon_pair(icon, other))
    return pairs, len(original) - len(pairs), len(unused)


def _texts(style: dict) -> list[dict]:
    return [r for r in style["runs"] if not r.get("icon")]


def match(original: dict, render: dict) -> dict:
    """How `render` differs from `original` (both `style_extract.extract` results): `runs` (a pair per matched text:
    `text`, `dx`, `dy`, `d_size`, `d_color`, the two colours, `split` when the render cut the text elsewhere),
    `missing` and `extra` (texts only one side has), `icons` (a pair per matched icon: `near`, the same numbers),
    `icons_missing` and `icons_extra` (counts)."""
    runs, missing, extra = _text_pairs(_texts(original), _texts(render))
    icons, icons_missing, icons_extra = _icon_pairs(original.get("icons", []), render.get("icons", []))
    return {"runs": runs, "missing": missing, "extra": extra, "icons": icons, "icons_missing": icons_missing,
            "icons_extra": icons_extra}


def worst_offset_pt(diffs: dict) -> float:
    """The largest shift, in points, of a matched text or icon; 0 when there is nothing to compare and infinity when
    the original has text and none of it was matched (a render that is not that CV is not within any distance)."""
    pairs = [p for p in (*diffs["runs"], *diffs["icons"]) if not p.get("split")]
    if not pairs:
        return math.inf if diffs["missing"] else 0.0
    return max(max(abs(p["dx"]), abs(p["dy"])) for p in pairs)


def _weight(p: dict) -> float:
    return abs(p["d_size"]) + abs(p["dx"]) / 10 + abs(p["dy"]) / 10


def _off(p: dict) -> bool:
    return abs(p["d_size"]) >= _OFF_SIZE or p["d_color"] > _OFF_COLOR or abs(p["dx"]) > _OFF_SHIFT or abs(p["dy"]) > _OFF_SHIFT


def feedback(diffs: dict, score: float, limit: int = _FEEDBACK_LIMIT) -> str:
    """What the next round tells the model: the blurred score, the elements that differ most (worst first), and
    what only one side has."""
    lines = [f"Blurred similarity to the original: {score:.2f} (1.00 = identical)."]
    worst = sorted((p for p in (*diffs["runs"], *diffs["icons"]) if not p.get("split") and _off(p)), key=lambda p: -_weight(p))
    for p in worst[:limit]:
        what = f"'{p['text'][:40]}'" if "text" in p else f"icon beside '{(p['near'] or '?')[:40]}'"
        lines.append(f"- {what}: size {p['d_size']:+}, colour {p['render_color']} (original {p['color']}), "
                     f"x {p['dx']:+}, y {p['dy']:+} (points)")
    for label, items in (("Missing from your rebuild", diffs["missing"]), ("Not in the original", diffs["extra"])):
        if items:
            lines.append(f"{label}: " + "; ".join(t[:40] for t in items[:limit]))
    for label, count in (("icons missing from your rebuild", diffs["icons_missing"]), ("icons not in the original", diffs["icons_extra"])):
        if count:
            lines.append(f"{count} {label}.")
    return "\n".join(lines)


# ---------- the images ----------

def _sum_squares(image: Image.Image) -> int:
    return sum(count * value * value for value, count in enumerate(image.histogram()))


def blurred_score(a: Image.Image, b: Image.Image, radius: float = BLUR_RADIUS) -> float:
    """How alike two page images look, 0 to 1: both grey and blurred (a shift of a pixel costs little), over their
    common part, the mean squared difference against what a blank page would differ by (on a mostly white page a plain
    difference is near 0 for any rebuild)."""
    size = (min(a.width, b.width), min(a.height, b.height))
    x, y = (im.convert("L").crop((0, 0, *size)).filter(ImageFilter.GaussianBlur(radius)) for im in (a, b))
    pixels = size[0] * size[1]
    if not pixels:
        return 1.0
    mse = _sum_squares(ImageChops.difference(x, y)) / pixels / 255**2
    blank = _sum_squares(ImageChops.invert(x)) / pixels / 255**2  # the ink the original has
    return min(1.0, max(0.0, 1 - mse / max(blank, 0.005)))


def pages_score(original: list[Image.Image], render: list[Image.Image]) -> float:
    """The mean `blurred_score` over the pages; a page only one side has scores 0."""
    count = max(len(original), len(render))
    if not count:
        return 1.0
    return sum(blurred_score(a, b) for a, b in zip(original, render)) / count


def page_images(pdf_path: Path, folder: Path) -> list[Image.Image]:
    """The pages of `pdf_path` as RGB images (150 dpi PNGs are left in `folder`)."""
    images = []
    for png in pdf_render.render_pdf_pages(pdf_path, folder):
        with Image.open(png) as im:
            images.append(im.convert("RGB"))
    return images


# ---------- the loop's rule ----------

def should_stop(scores: list[float], worst_offset: float, cap: int = CAP) -> bool:
    """Whether the rebuild loop is done after the rounds with these blurred `scores`, the last round's matched elements
    being `worst_offset` points off at most: at `cap` rounds, when that is within `WITHIN_PT`, or when the last round
    gained less than `MIN_GAIN` over the best round before it."""
    if not scores:
        return False
    if len(scores) >= cap or worst_offset <= WITHIN_PT:
        return True
    return len(scores) > 1 and scores[-1] - max(scores[:-1]) < MIN_GAIN


def best_round(scores: list[float]) -> int:
    """The index of the best round (the first when several tie).

    Raises:
        ValueError: there are no rounds.
    """
    if not scores:
        raise ValueError("no rounds")
    return scores.index(max(scores))
