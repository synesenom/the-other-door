"""Trace a rendered icon into an SVG path (#148): Pillow only, no numpy, nothing read or written.

An icon of a CV (an icon-font glyph or a small drawing) is rendered large from its PDF page and cut out; `trace`
turns the pixels that differ from the ground into closed loops of straight segments, in points. The exact
boundary of the ink is followed along pixel edges, then simplified (Ramer-Douglas-Peucker, one pixel), so a
diagonal is one segment and a curve a few dozen. Holes are loops of their own, to be filled `evenodd`.
"""

from __future__ import annotations

import math
import statistics
from collections import deque

from PIL import Image

_MIN_DISTANCE = 40  # a difference from the ground under this is not ink (the fainter an icon, the likelier a smudge)
_MIN_COMPONENT = 4  # pixels: fewer is a speck


def _ink_mask(image: Image.Image) -> list[list[bool]] | None:
    """Which pixels differ from the ground (the median colour of the image's border) by at least half the largest
    difference, and by 40 of 255; None when nothing does."""
    w, h = image.size
    px = image.load()
    border = [px[x, y] for x in range(w) for y in (0, h - 1)] + [px[x, y] for y in range(h) for x in (0, w - 1)]
    ground = tuple(statistics.median(p[c] for p in border) for c in range(3))
    dist = [[max(abs(px[x, y][c] - ground[c]) for c in range(3)) for x in range(w)] for y in range(h)]
    peak = max(max(row) for row in dist)
    if peak < _MIN_DISTANCE:
        return None
    limit = max(0.5 * peak, _MIN_DISTANCE)
    return [[d >= limit for d in row] for row in dist]


def _drop_specks(mask: list[list[bool]]) -> None:
    """Clear, in place, the 8-connected groups of fewer than four pixels."""
    h, w = len(mask), len(mask[0])
    seen = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if not mask[y][x] or seen[y][x]:
                continue
            group, queue = [], deque([(x, y)])
            seen[y][x] = True
            while queue:
                cx, cy = queue.popleft()
                group.append((cx, cy))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and mask[ny][nx] and not seen[ny][nx]:
                            seen[ny][nx] = True
                            queue.append((nx, ny))
            if len(group) < _MIN_COMPONENT:
                for gx, gy in group:
                    mask[gy][gx] = False


def _loops(mask: list[list[bool]]) -> list[list[tuple[int, int]]]:
    """The boundary of the ink as closed loops of pixel corners: every pixel edge with ink on one side only, as a
    directed edge (so an outer boundary runs clockwise and a hole counter-clockwise), chained end to start."""
    h, w = len(mask), len(mask[0])

    def ink(x: int, y: int) -> bool:
        return 0 <= x < w and 0 <= y < h and mask[y][x]

    out: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for y in range(h):
        for x in range(w):
            if not mask[y][x]:
                continue
            if not ink(x, y - 1):
                out.setdefault((x, y), []).append((x + 1, y))
            if not ink(x + 1, y):
                out.setdefault((x + 1, y), []).append((x + 1, y + 1))
            if not ink(x, y + 1):
                out.setdefault((x + 1, y + 1), []).append((x, y + 1))
            if not ink(x - 1, y):
                out.setdefault((x, y + 1), []).append((x, y))
    loops = []
    while out:
        start = next(iter(out))
        loop, here = [start], start
        while True:
            ends = out[here]
            nxt = ends.pop()
            if not ends:
                del out[here]
            if nxt == start:
                break
            loop.append(nxt)
            here = nxt
        loops.append(loop)
    return loops


def _corners(loop: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The loop without the points on a straight line between their neighbours."""
    n = len(loop)
    return [p for i, p in enumerate(loop)
            if (loop[i - 1][0] - p[0]) * (loop[(i + 1) % n][1] - p[1]) != (loop[i - 1][1] - p[1]) * (loop[(i + 1) % n][0] - p[0])]


def _rdp(points: list[tuple[int, int]], epsilon: float) -> list[tuple[int, int]]:
    if len(points) < 3:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    length = math.hypot(x1 - x0, y1 - y0)
    far, at = 0.0, 0
    for i in range(1, len(points) - 1):
        x, y = points[i]
        d = abs((x1 - x0) * (y0 - y) - (x0 - x) * (y1 - y0)) / length if length else math.hypot(x - x0, y - y0)
        if d > far:
            far, at = d, i
    if far <= epsilon:
        return [points[0], points[-1]]
    return _rdp(points[: at + 1], epsilon)[:-1] + _rdp(points[at:], epsilon)


def _simplify(loop: list[tuple[int, int]], epsilon: float) -> list[tuple[int, int]]:
    """RDP on a closed loop: cut at the corner farthest from the first, simplify the two halves."""
    if len(loop) < 4:
        return loop
    a = loop[0]
    mid = max(range(len(loop)), key=lambda i: math.hypot(loop[i][0] - a[0], loop[i][1] - a[1]))
    first, second = _rdp(loop[: mid + 1], epsilon), _rdp(loop[mid:] + [a], epsilon)
    return first[:-1] + second[:-1]


def _number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def trace(image: Image.Image, scale: float, fill: str) -> dict | None:
    """The ink of *image* (rendered at *scale* pixels per point) as `{"bbox": [x0, y0, x1, y1] in pixels, "d": an
    SVG path in points from the ink's top left, "viewBox": "0 0 w h" in points, "fill", "fill_rule": "evenodd"}`;
    None when nothing in it stands out from its ground."""
    mask = _ink_mask(image.convert("RGB"))
    if mask is None:
        return None
    _drop_specks(mask)
    loops = _loops(mask)
    if not loops:
        return None
    xs = [x for loop in loops for x, _ in loop]
    ys = [y for loop in loops for _, y in loop]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    parts = []
    for loop in loops:
        points = _simplify(_corners(loop), 1.0)
        coords = [f"{_number((x - x0) / scale)} {_number((y - y0) / scale)}" for x, y in points]
        parts.append("M" + " L".join(coords) + " Z" if len(coords) > 1 else "")
    return {"bbox": [x0, y0, x1, y1], "d": " ".join(p for p in parts if p),
            "viewBox": f"0 0 {_number((x1 - x0) / scale)} {_number((y1 - y0) / scale)}", "fill": fill,
            "fill_rule": "evenodd"}
