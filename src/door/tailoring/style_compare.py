"""Compare a rebuilt CV's render with the original (#204, epic #144): pure and offline, Pillow only.

Both sides are `style_extract.extract` results (`runs` and `icons`, points, origin top left). `match` pairs the text
runs by their normalised text (the nearest run of the same text when there are several) and the icons by the text
they sit beside, then by position, and says how each pair differs: `dx`, `dy` (the render's box minus the original's),
`d_size`, and `d_color` (`style_trace.distance`, the largest channel difference). `pages_score` (grey and its text
strokes, blurred, each original page at its best vertical shift) says how alike the page images look, `feedback` is what the next round tells the
model, and `should_stop` / `best_round` are the loop's stopping rule: stop at `CAP` rounds, when every matched element
is within `WITHIN_PT` points, or when the last round gained under `MIN_GAIN` over the best before it (once the best scored `GOOD`); the best round is kept, and a build whose best is under `FLOOR` is failed.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

from door.tailoring import pdf_render, readability, style_trace

CAP = 7  # rounds
WITHIN_PT = 2.0  # every matched element this close: nothing left to fix
# a round that adds less than this over the best before it is not worth another: half of the old 0.005, as the blurred score
# (which weighs the difference against the ink) roughly halves what a round gains, so the same sensitivity
MIN_GAIN = 0.0025
# the small-gain rule applies only once the best round scored this, a good rebuild (0.88-0.99 in #238's real runs): below
# it a flat or worse round goes on to the cap with the feedback (a broken first draft scored 0.31 then 0.01, #243)
GOOD = 0.8
# a build whose best round scored under this is failed, nothing written (#241): on the page score, rebuilds that looked
# like their CV scored 0.54-0.99 in real runs and broken ones 0.10-0.49 (columns swapped: 0.487). Re-scored with the
# strokes (#250), 64 saved renders: every original against itself 1.0, the rebuilds above GOOD stay above it (0.81-0.99)
# but one whose lines drift a few points beside a side band (0.98 to 0.77), squashed main columns 0.17-0.26 (were 0.46-0.49, their page 1 0.97)
FLOOR = 0.5
BLUR_RADIUS = 4.0  # pixels at the render's 150 dpi
SHIFT_REACH = 0.15  # of a page's height: how far `pages_score` looks up and down for where an original page sits
# the render's first page beyond the original's count holding this share of an original page's ink or less is a few
# lines over and costs that share; any other page beyond the count costs a whole page
OVERFLOW_SHARE = 0.25
# `_alike`'s least ink for `_strokes`: thin marks hold a tenth of the ink of the fills or less (a real page's strokes
# 0.013-0.025, a page of a few short lines 0.001)
_STROKES_FLOOR = 0.0005
_SEARCH_SCALE = 4  # the shift is searched on images this many times smaller
_FEEDBACK_LIMIT = 12
MIN_PART = 5  # characters: a shorter text is not paired by being part of another ("2019" is in many runs)
# a difference smaller than these is not worth telling the model about
_OFF_SIZE, _OFF_COLOR, _OFF_SHIFT = 0.5, 40, 6.0


def _page(item: dict) -> int:
    return item.get("page", 1)


def _centre(icon: dict) -> tuple[float, float]:
    b = icon["bbox"]
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _extent(icon: dict) -> float:
    b = icon["bbox"]
    return max(b[2] - b[0], b[3] - b[1])


def _offsets(a: dict, b: dict) -> dict:
    """What a pair of an original's element and the render's has in common: the shift of the box, the colours, and the
    two pages when they differ (an element on another page is off by any distance)."""
    pair = {"dx": round(b["bbox"][0] - a["bbox"][0], 1), "dy": round(b["bbox"][1] - a["bbox"][1], 1),
            "d_color": style_trace.distance(style_trace.channels(a["color"]), style_trace.channels(b["color"])),
            "color": a["color"], "render_color": b["color"]}
    if _page(a) != _page(b):
        pair["page"], pair["render_page"] = _page(a), _page(b)
    return pair


def _run_pair(a: dict, b: dict) -> dict:
    return {"text": a["text"], "d_size": round(b["size"] - a["size"], 1), **_offsets(a, b)}


def _icon_pair(a: dict, b: dict) -> dict:
    return {"near": (a.get("near") or {}).get("text"), "d_size": round(_extent(b) - _extent(a), 1), **_offsets(a, b)}


def _greedy(left: list[dict], right: list[dict], key, dist) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """Pair `left` with `right` elements that have the same `key` (None pairs nothing), the closest pairs first, so
    that of several alike elements each takes its own partner. Returns the pairs and what is left on each side."""
    buckets: dict = {}
    for j, b in enumerate(right):
        k = key(b)
        if k is not None:
            buckets.setdefault(k, []).append(j)
    candidates = sorted((dist(a, right[j]), i, j) for i, a in enumerate(left) if key(a) is not None
                        for j in buckets.get(key(a), ()))
    used_left, used_right, pairs = set(), set(), []
    for _, i, j in candidates:
        if i not in used_left and j not in used_right:
            used_left.add(i)
            used_right.add(j)
            pairs.append((left[i], right[j]))
    return (pairs, [a for i, a in enumerate(left) if i not in used_left],
            [b for j, b in enumerate(right) if j not in used_right])


def _origin_distance(a: dict, b: dict) -> float:
    return math.hypot(a["bbox"][0] - b["bbox"][0], a["bbox"][1] - b["bbox"][1])


def _text_pairs(original: list[dict], render: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    pairs: list[dict] = []
    missing, rest = original, render
    for key in (lambda r: (readability.normalise(r["text"]), _page(r)), lambda r: readability.normalise(r["text"])):  # on the same page first
        found, missing, rest = _greedy(missing, rest, key, _origin_distance)
        pairs += [_run_pair(a, b) for a, b in found]
    still_missing: list[str] = []
    joined: list[dict] = []  # renders that hold several originals: they stay there for the next one
    for run in missing:  # a run the render split or joined differently: pair it with the runs that hold it or are held by it
        text = readability.normalise(run["text"])
        if len(text) < MIN_PART:
            still_missing.append(run["text"])
            continue
        parts = [r for r in rest if len(readability.normalise(r["text"])) >= MIN_PART and readability.normalise(r["text"]) in text]
        hosts = [r for r in (*rest, *joined) if text in readability.normalise(r["text"])]
        if parts:  # the render cut it in pieces: all of them belong to it, the first one is where it starts
            hit = min(parts, key=lambda r: (_page(r), r["bbox"][1], r["bbox"][0]))
            rest = [r for r in rest if r not in parts]
        elif hosts:  # the render joined it with other text: it starts where its place in that text is
            host = min(hosts, key=lambda r: _origin_distance(run, r))
            held = readability.normalise(host["text"])
            x0, x1 = host["bbox"][0], host["bbox"][2]
            hit = {**host, "bbox": [x0 + (x1 - x0) * held.index(text) / len(held), *host["bbox"][1:]]}
            if host in rest:
                rest.remove(host)
                joined.append(host)
        else:
            still_missing.append(run["text"])
            continue
        pairs.append({**_run_pair(run, hit), "split": True})
    return pairs, still_missing, [r["text"] for r in rest]


def _icon_pairs(original: list[dict], render: list[dict]) -> tuple[list[dict], int, int]:
    def near(icon: dict) -> str:
        return readability.normalise((icon.get("near") or {}).get("text") or "")

    def far(a: dict, b: dict) -> float:
        (ax, ay), (bx, by) = _centre(a), _centre(b)
        return math.hypot(ax - bx, ay - by)

    pairs: list[dict] = []
    left, right = original, render
    # beside the same text first, then by position, each on the same page before any
    for key in (lambda i: (near(i), _page(i)) if near(i) else None, lambda i: near(i) or None, _page, lambda i: 0):
        found, left, right = _greedy(left, right, key, far)
        pairs += [_icon_pair(a, b) for a, b in found]
    return pairs, len(left), len(right)


def _texts(style: dict) -> list[dict]:
    return [r for r in style["runs"] if not r.get("icon")]


def match(original: dict, render: dict) -> dict:
    """How `render` differs from `original` (both `style_extract.extract` results): `runs` (a pair per matched text:
    `text`, `dx`, `dy`, `d_size`, `d_color`, the two colours, `split` when the render cut the text elsewhere),
    `missing` and `extra` (texts only one side has), `icons` (a pair per matched icon: `near`, the same numbers),
    `icons_missing` and `icons_extra` (counts), `pages` (the two page counts, None where one is not known)."""
    runs, missing, extra = _text_pairs(_texts(original), _texts(render))
    icons, icons_missing, icons_extra = _icon_pairs(original.get("icons", []), render.get("icons", []))
    return {"runs": runs, "missing": missing, "extra": extra, "icons": icons, "icons_missing": icons_missing,
            "icons_extra": icons_extra, "pages": (original.get("page_count"), render.get("page_count"))}


def worst_offset_pt(diffs: dict) -> float:
    """The largest shift, in points, of a matched text or icon; 0 when there is nothing to compare and infinity when
    the original has text and none of it was matched (a render that is not that CV is not within any distance)."""
    pairs = [*diffs["runs"], *diffs["icons"]]
    if not pairs:
        return math.inf if diffs["missing"] else 0.0
    return max(math.inf if "render_page" in p else max(abs(p["dx"]), abs(p["dy"])) for p in pairs)


def _weight(p: dict) -> float:
    return math.inf if "render_page" in p else abs(p["d_size"]) + abs(p["dx"]) / 10 + abs(p["dy"]) / 10


def _off(p: dict) -> bool:
    return "render_page" in p or abs(p["d_size"]) >= _OFF_SIZE or p["d_color"] > _OFF_COLOR or abs(p["dx"]) > _OFF_SHIFT or abs(p["dy"]) > _OFF_SHIFT


def feedback(diffs: dict, score: float) -> str:
    """What the next round tells the model: the blurred score, a page count unlike the original's (every line after a
    break shifts with it, so it comes first), the elements that differ most (worst first), and what only one side has."""
    lines = [f"Blurred similarity to the original: {score:.2f} (1.00 = identical)."]
    original_pages, render_pages = diffs["pages"]
    if isinstance(original_pages, int) and isinstance(render_pages, int) and original_pages != render_pages:
        how = "tighten the line height, the spacing and the margins" if render_pages > original_pages else "loosen the spacing"
        runs_to = "1 page" if render_pages == 1 else f"{render_pages} pages"
        lines.append(f"Fix this first: your rebuild runs to {runs_to}, the original has {original_pages}: {how} until it "
                     f"has {original_pages}, like the original's.")
    worst = sorted((p for p in (*diffs["runs"], *diffs["icons"]) if _off(p)), key=lambda p: -_weight(p))
    for p in worst[:_FEEDBACK_LIMIT]:
        what = f"'{p['text'][:40]}'" if "text" in p else f"icon beside '{(p['near'] or '?')[:40]}'"
        if "render_page" in p:
            lines.append(f"- {what}: on page {p['render_page']}, original page {p['page']}")
            continue
        lines.append(f"- {what}: size {p['d_size']:+}, colour {p['render_color']} (original {p['color']}), "
                     f"x {p['dx']:+}, y {p['dy']:+} (points)")
    for label, items in (("Missing from your rebuild", diffs["missing"]), ("Not in the original", diffs["extra"])):
        if items:
            lines.append(f"{label}: " + "; ".join(t[:40] for t in items[:_FEEDBACK_LIMIT]))
    for label, count in (("icons missing from your rebuild", diffs["icons_missing"]), ("icons not in the original", diffs["icons_extra"])):
        if count:
            lines.append(f"{count} {label}.")
    return "\n".join(lines)


# ---------- the images ----------

def _sum_squares(image: Image.Image) -> int:
    return sum(count * value * value for value, count in enumerate(image.histogram()))


def _grey(image: Image.Image, width: int) -> Image.Image:
    return image.convert("L").crop((0, 0, width, image.height)).filter(ImageFilter.GaussianBlur(BLUR_RADIUS))


def _strokes(image: Image.Image, width: int) -> Image.Image:
    """Where the page's thin marks are, whatever their colour, dark on white and blurred like `_grey`: each pixel's local
    contrast (the largest minus the smallest grey of its 3x3 neighbours), so text and rules count and the inside of a
    filled area does not (#250: a big coloured band that matches must not hide a main column laid out otherwise)."""
    grey = image.convert("L").crop((0, 0, width, image.height))
    contrast = ImageChops.subtract(grey.filter(ImageFilter.MaxFilter(3)), grey.filter(ImageFilter.MinFilter(3)))
    return ImageChops.invert(contrast).filter(ImageFilter.GaussianBlur(BLUR_RADIUS))


def _ink(image: Image.Image) -> int:
    return _sum_squares(ImageChops.invert(image))


def _alike(x: Image.Image, y: Image.Image, floor: float = 0.005) -> float:
    """How alike two grey blurred images of one size look, 0 to 1 (the blur makes a shift of a pixel cost little): the
    mean squared difference against the ink of the two together (on a mostly white page a plain difference is near 0
    for any rebuild; a rebuild further off than a blank page still scores above 0)."""
    pixels = x.width * x.height
    if not pixels:
        return 1.0
    mse = _sum_squares(ImageChops.difference(x, y)) / pixels / 255**2
    ink = (_ink(x) + _ink(y)) / pixels / 255**2
    return 1 - mse / max(ink, floor)


def _best_shift(page: Image.Image, strip: Image.Image, top: int, reach: int) -> int:
    """The row of `strip` where `page` matches best, about `reach` rows of `top` at most (the nearest of equals):
    searched on images `_SEARCH_SCALE` times smaller (the blur makes the difference smooth), then row by row around
    the best."""
    def search(rows: range, scale: int) -> int:
        size = (max(page.width // scale, 1), max(page.height // scale, 1))
        target = page.resize(size)

        def error(row: int) -> int:
            return _sum_squares(ImageChops.difference(target, strip.crop((0, row, page.width, row + page.height)).resize(size)))
        return min(rows, key=lambda row: (error(row), abs(row - top)))

    coarse = search(range(top - reach // _SEARCH_SCALE * _SEARCH_SCALE, top + reach + 1, _SEARCH_SCALE), _SEARCH_SCALE)
    return search(range(coarse - _SEARCH_SCALE + 1, coarse + _SEARCH_SCALE), 1)


def pages_score(original: list[Image.Image], render: list[Image.Image]) -> float:
    """How alike two documents look, 0 to 1: the mean score of the original's pages, each against the render's pages
    laid end to end at the vertical shift (up to `SHIFT_REACH` of a page) where it matches best, so that a rebuild a few
    lines too long is not scored as if every line after the first break were wrong (#244). A page's score is the mean
    of two blurred scores (`_alike`): of the grey page (its fills and colours) and of its `_strokes` (where its text and
    rules are, so a matching band does not hide a squashed or moved text column, #250). An
    original page with nothing under it scores 0. What the render holds outside those windows counts as pages scoring
    0: on each of the original's count of pages, the share of the original's mean page its ink makes (at most one); a
    page beyond that count costs a whole page, but for the first one when it holds `OVERFLOW_SHARE` of a page or less
    (a few lines over, which costs its share): a rebuild far too long scores low."""
    if not original or not render:
        return 1.0 if not original and not render else 0.0
    width = min(im.width for im in (*original, *render))
    pages = [_grey(im, width) for im in original]
    step = render[0].height
    pad = max(page.height for page in pages)  # white above and below: room to shift into, and for a taller page
    strip = Image.new("L", (width, step * len(render) + 2 * pad), 255)
    marks = strip.copy()  # the same, of the render's `_strokes`
    for i, im in enumerate(render):
        strip.paste(_grey(im, width).crop((0, 0, width, step)), (0, pad + i * step))
        marks.paste(_strokes(im, width).crop((0, 0, width, step)), (0, pad + i * step))
    left = strip.copy()  # the render with every window compared painted white: what no original page was compared with
    scores = []
    for i, (image, page) in enumerate(zip(original, pages)):
        row = _best_shift(page, strip, pad + i * step, round(SHIFT_REACH * step))
        window = (0, row, width, row + page.height)
        fill, text = _alike(page, strip.crop(window)), _alike(_strokes(image, width), marks.crop(window), _STROKES_FLOOR)
        scores.append((fill + text) / 2)
        left.paste(255, window)
    page_ink = sum(map(_ink, pages)) / len(pages) or 1
    extra = 0.0
    for i in range(len(render)):
        share = min(_ink(left.crop((0, pad + i * step, width, pad + (i + 1) * step))) / page_ink, 1.0)
        a_few_lines_over = i == len(pages) and share <= OVERFLOW_SHARE
        extra += 1.0 if i >= len(pages) and not a_few_lines_over else share
    return sum(scores) / (len(pages) + extra)


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
    gained less than `MIN_GAIN` over the best round before it, once the best round has reached `GOOD`."""
    if not scores:
        return False
    if len(scores) >= cap or worst_offset <= WITHIN_PT:
        return True
    return len(scores) > 1 and max(scores) >= GOOD and scores[-1] - max(scores[:-1]) < MIN_GAIN


def best_round(scores: list[float]) -> int:
    """The index of the best round (the first when several tie).

    Raises:
        ValueError: there are no rounds.
    """
    if not scores:
        raise ValueError("no rounds")
    return scores.index(max(scores))
