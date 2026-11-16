"""Read a CV PDF's style as facts (#148, epic #144): fonts, sizes, colours, margins, columns, headings, drawn
shapes, icons as SVG paths, the photo. Pure and offline: pypdfium2 and Pillow, nothing written, no network.

`extract(pdf_path)` returns one dict (schema version 1, points, the origin at the top left, colours `#rrggbb`):
`verdict` first (`style_verdict` says when there is nothing to copy: a scan or a LinkedIn export; the other
keys are then left out), then `runs` (one per piece of text on a line), `fonts`, `page` (size, margins, bleed,
background), `colors` (text, accent), `name`, `columns` (bands), `headings` and `heading_style`, `shapes`, `icons`
(SVG paths next to the text they belong to), `photo`. Fonts are only described (family, weight, italic, serif, fixed); looking
them up is another step. The icon tracer is `door.tailoring.style_trace`.
"""

from __future__ import annotations

import ctypes
import math
import re
from pathlib import Path

import pypdfium2.raw as raw

from door import i18n
from door.tailoring import pdf_render, style_trace

VERSION = 1
_INTERNAL = {"baseline", "lead", "trail", "parts", "gaps"}  # what the analysis keeps on a run and the result does not

_WEIGHTS = [  # longest names first: "extrabold" holds "bold"
    ("extrablack", 950), ("ultrablack", 950), ("extralight", 200), ("ultralight", 200), ("extrabold", 800),
    ("ultrabold", 800), ("semibold", 600), ("demibold", 600), ("hairline", 100), ("regular", 400),
    ("medium", 500), ("normal", 400), ("light", 300), ("heavy", 800), ("black", 900), ("bold", 700),
    ("thin", 100), ("book", 400),
]
_STYLE_WORDS = {w for w, _ in _WEIGHTS} | {"italic", "oblique", "roman", "ital", "it"}
# what a bullet of a list is set as: no icon, and no column of its own
_BULLETS = set("\u2022\u00b7\u2023\u25e6\u25aa\u25cf\u25cb\u25a0\u25a1\u2013\u2219-*")
_SERIF_NAMES = re.compile(r"times|georgia|garamond|palatino|cambria|minion|baskerville|bookman|caslon|didot|(?<!sans)serif", re.I)
_FIXED_NAMES = re.compile(r"courier|mono|consolas|typewriter|menlo", re.I)
_FLAG_FIXED, _FLAG_SERIF, _FLAG_ITALIC, _FLAG_FORCE_BOLD = 0x1, 0x2, 0x40, 0x40000


# ---------- fonts ----------

def font_facts_from_name(name: str) -> dict:
    """Family, weight and italic as a font's base name tells them (`ABCDEF+Lato-Light`, `Arial-BoldMT`)."""
    base = name.split("+", 1)[-1]
    parts = re.split(r"[-,]", base, maxsplit=1)
    family, style = parts[0], (parts[1] if len(parts) > 1 else "")
    family = re.sub(r"(MT|PS)$", "", family).strip()
    lowered = style.lower().replace(" ", "")
    weight = next((w for word, w in _WEIGHTS if word in lowered), 400)
    if weight == 950:
        weight = 900
    italic = "italic" in lowered or "oblique" in lowered
    return {"family": family, "weight": weight, "italic": italic}


def _font_facts(font) -> dict:
    name = font.get_base_name().split("+", 1)[-1]
    facts = font_facts_from_name(name)
    flags = raw.FPDFFont_GetFlags(font.raw)
    family = font.get_family_name() if raw.FPDFFont_GetIsEmbedded(font.raw) else ""
    if family and not any(w in family.lower().split() for w in _STYLE_WORDS):
        facts["family"] = family
    if flags & _FLAG_FORCE_BOLD:
        facts["weight"] = max(facts["weight"], 700)
    facts["italic"] = facts["italic"] or bool(flags & _FLAG_ITALIC)
    angle = ctypes.c_int()
    if raw.FPDFFont_GetItalicAngle(font.raw, angle) and angle.value:
        facts["italic"] = True
    serif, fixed = bool(flags & _FLAG_SERIF), bool(flags & _FLAG_FIXED)
    if not raw.FPDFFont_GetIsEmbedded(font.raw):  # a standard font has no descriptor: its name says
        serif, fixed = serif or bool(_SERIF_NAMES.search(name)), fixed or bool(_FIXED_NAMES.search(name))
    return {"font": name, **facts, "serif": serif, "fixed": fixed,
            "embedded": bool(raw.FPDFFont_GetIsEmbedded(font.raw))}


# ---------- reading the page objects ----------

def _rgb(getter, obj) -> str:
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    getter(obj.raw, r, g, b, a)
    return f"#{r.value:02x}{g.value:02x}{b.value:02x}"


def _bbox(obj, height: float) -> list[float]:
    left, bottom, right, top = obj.get_bounds()
    return [round(left, 1), round(height - top, 1), round(right, 1), round(height - bottom, 1)]


def _text_runs(page, number: int, height: float) -> list[dict]:
    """The visible text objects of a page as runs (the invisible ones, render mode 3, an OCR layer's, are left out)."""
    textpage = page.get_textpage()
    runs = []
    try:
        for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT]):
            if raw.FPDFTextObj_GetTextRenderMode(obj.raw) == 3:
                continue
            obj.textpage = textpage
            raw_text = obj.extract()
            text = raw_text.strip()
            if not text:
                continue
            m = obj.get_matrix()
            size = round(obj.get_font_size() * math.hypot(m.c, m.d), 1)
            runs.append({"page": number, "text": text, "bbox": _bbox(obj, height), "size": size,
                         "color": _rgb(raw.FPDFPageObj_GetFillColor, obj), "rotated": abs(m.b) > abs(m.a),
                         "baseline": round(height - m.f, 1), "icon": False,
                         "lead": raw_text[:1].isspace(), "trail": raw_text[-1:].isspace(), **_font_facts(obj.get_font())})
    finally:
        textpage.close()
    return runs


def merge_runs(runs: list[dict]) -> list[dict]:
    """Chromium and Skia write one text object per glyph or word: join those on one line with the same font,
    size, colour and style whose gap is under a word space (a gap over a fifth of the size becomes a space).
    Capitals set with letter spacing come out as glyph objects each a gap apart: `_respaced` reads them as words."""
    out: list[dict] = []
    for run in sorted(runs, key=lambda r: (r["page"], r["baseline"], r["bbox"][0])):
        last = out[-1] if out else None
        if last and _same_style(last, run) and abs(run["baseline"] - last["baseline"]) <= 0.3 * run["size"]:
            gap = run["bbox"][0] - last["bbox"][2]
            if -0.3 * run["size"] <= gap <= 0.6 * run["size"]:
                space = " " if gap > 0.2 * run["size"] or last["trail"] or run["lead"] else ""
                last.update(text=last["text"] + space + run["text"], trail=run["trail"],
                            bbox=[last["bbox"][0], min(last["bbox"][1], run["bbox"][1]), run["bbox"][2],
                                  max(last["bbox"][3], run["bbox"][3])])
                last["parts"].append(run["text"])
                last["gaps"].append(gap)
                continue
        out.append({**run, "parts": [run["text"]], "gaps": []})
    for run in out:
        run["text"] = _respaced(run)
    return out


def _respaced(run: dict) -> str:
    """The text of a run made of glyph objects of one or two characters (four or more, or two single letters), in
    capitals, with gaps that average at least 0.15 of the size: letter-spaced, so a space only where the gap is
    well over the others."""
    parts, gaps = run["parts"], run["gaps"]
    if not (len(parts) >= 4 or (len(parts) == 2 and all(len(p) == 1 for p in parts))) or not run["text"].isupper() or sum(len(p) <= 2 for p in parts) < 0.7 * len(parts) \
            or sum(gaps) / len(gaps) < 0.15 * run["size"]:
        return run["text"]
    median = sorted(gaps)[len(gaps) // 2]
    return parts[0] + "".join((" " if g > max(2 * median, 0.45 * run["size"]) else "") + p for g, p in zip(gaps, parts[1:]))


def _same_style(a: dict, b: dict) -> bool:
    keys = ("page", "font", "size", "color", "weight", "italic", "rotated")
    return all(a[k] == b[k] for k in keys)


# ---------- drawn shapes ----------

_RULE_MAX, _RULE_MIN_LENGTH, _DOT_MAX = 3.5, 20.0, 10.0


def _segments(obj, height: float) -> list[tuple[int, float, float, bool]]:
    """A path's segments as (type, x, y, closes) in page points, the origin at the top left."""
    m = obj.get_matrix()
    out = []
    for i in range(raw.FPDFPath_CountSegments(obj.raw)):
        seg = raw.FPDFPath_GetPathSegment(obj.raw, i)
        x, y = ctypes.c_float(), ctypes.c_float()
        raw.FPDFPathSegment_GetPoint(seg, x, y)
        out.append((raw.FPDFPathSegment_GetType(seg), m.a * x.value + m.c * y.value + m.e,
                    height - (m.b * x.value + m.d * y.value + m.f), bool(raw.FPDFPathSegment_GetClose(seg))))
    return out


def _dash(obj) -> list[float] | None:
    count = raw.FPDFPageObj_GetDashCount(obj.raw)
    if count <= 0:
        return None
    array = (ctypes.c_float * count)()
    raw.FPDFPageObj_GetDashArray(obj.raw, array, count)
    return [round(v, 2) for v in array]


def _axis_aligned(points: list[tuple[float, float]]) -> bool:
    return all(abs(a[0] - b[0]) < 0.05 or abs(a[1] - b[1]) < 0.05 for a, b in zip(points, points[1:] + points[:1]))


def _round(segs, width: float, height: float) -> bool:
    """Whether the points a path passes through lie on a circle around the middle of its box."""
    on_curve, bezier = [], 0
    for kind, x, y, _ in segs:
        bezier = bezier + 1 if kind == raw.FPDF_SEGMENT_BEZIERTO else 0
        if kind != raw.FPDF_SEGMENT_BEZIERTO or bezier % 3 == 0:
            on_curve.append((x, y))
    cx, cy = (min(x for x, _ in on_curve) + max(x for x, _ in on_curve)) / 2, (min(y for _, y in on_curve) + max(y for _, y in on_curve)) / 2
    radii = [math.hypot(x - cx, y - cy) for x, y in on_curve]
    return min(radii) > 0 and max(radii) / min(radii) <= 1.2


def _shape_kind(segs, width: float, height: float, fill, stroke_width: float, stroked: bool, dash) -> tuple[str, bool] | None:
    """(kind, rounded) of a path from its geometry, or None for anything else (an icon candidate)."""
    curves = sum(t == raw.FPDF_SEGMENT_BEZIERTO for t, *_ in segs)
    points = [(x, y) for _, x, y, _ in segs]
    if dash and stroked:
        return "dash", False
    if not curves and len(points) <= 3 and stroked and not fill and max(width, height) >= _RULE_MIN_LENGTH \
            and stroke_width <= _RULE_MAX:
        return "rule", False
    if fill and not curves and min(width, height) <= _RULE_MAX and max(width, height) >= _RULE_MIN_LENGTH \
            and _axis_aligned(points):
        return "rule", False
    if fill and width <= _DOT_MAX and height <= _DOT_MAX and abs(width - height) <= 1 and (curves >= 8 or len(points) >= 8) \
            and _round(segs, width, height):
        return "dot", False
    if not curves and 4 <= len(points) <= 5 and _axis_aligned(points[:4]):
        return "box", False
    lines = [((a[1], a[2]), (b[1], b[2])) for a, b in zip(segs, segs[1:]) if b[0] == raw.FPDF_SEGMENT_LINETO]
    if curves and curves // 3 <= 8 and abs(width - height) <= 1 and not lines:
        return "box", True  # a circle, bigger than a dot
    if curves and curves // 3 <= 8 and len(lines) >= 3 and all(abs(a[0] - b[0]) < 0.05 or abs(a[1] - b[1]) < 0.05 for a, b in lines):
        return "box", True  # a rectangle with round corners
    return None


def _read_shapes(page, number: int, height: float) -> list[dict]:
    """Every path of a page: its kind (rule, dash, dot, box; None: left for the icon pass), colours, stroke width,
    dash pattern, the segments and a box from the points (a stroke's own width not in it)."""
    out = []
    for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_PATH]):
        segs = _segments(obj, height)
        if len(segs) < 2:
            continue
        fill, stroke = ctypes.c_int(), ctypes.c_int()
        raw.FPDFPath_GetDrawMode(obj.raw, fill, stroke)
        if not (fill.value or stroke.value):
            continue
        m = obj.get_matrix()
        stroke_width = ctypes.c_float()
        raw.FPDFPageObj_GetStrokeWidth(obj.raw, stroke_width)
        scale = math.sqrt(abs(m.a * m.d - m.b * m.c)) or 1.0
        xs, ys = [p[1] for p in segs], [p[2] for p in segs]
        bbox = [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]
        width_pt = round(stroke_width.value * scale, 2) if stroke.value else 0.0
        fill_color = _rgb(raw.FPDFPageObj_GetFillColor, obj) if fill.value else None
        dash = _dash(obj) if stroke.value else None
        found = _shape_kind(segs, bbox[2] - bbox[0], bbox[3] - bbox[1], fill_color, width_pt, bool(stroke.value), dash)
        thickness = round(min(bbox[2] - bbox[0], bbox[3] - bbox[1]), 2)
        out.append({"page": number, "kind": found[0] if found else None, "bbox": bbox, "fill": fill_color,
                    "stroke": _rgb(raw.FPDFPageObj_GetStrokeColor, obj) if stroke.value else None,
                    "width": width_pt or (thickness if found and found[0] == "rule" else 0.0), "dash": dash,
                    "rounded": bool(found and found[1]), "segments": segs})
    return out


def _page_background(shapes: list[dict], size: list[float]) -> tuple[str | None, list[dict]]:
    """The fill of a path that covers the page (90% of it), and the shapes without it."""
    area = size[0] * size[1]
    for shape in shapes:
        x0, y0, x1, y1 = shape["bbox"]
        if shape["fill"] and (x1 - x0) * (y1 - y0) >= 0.9 * area:
            return shape["fill"], [s for s in shapes if s is not shape]
    return None, shapes


def _bleed(shapes: list[dict], size: list[float]) -> list[str]:
    """The sides of the page a drawn shape runs off to: touching the edge and covering half of it or more."""
    sides = []
    for shape in shapes:
        x0, y0, x1, y1 = shape["bbox"]
        for side, touches, extent, whole in (("left", x0 <= 1, y1 - y0, size[1]), ("right", x1 >= size[0] - 1, y1 - y0, size[1]),
                                              ("top", y0 <= 1, x1 - x0, size[0]), ("bottom", y1 >= size[1] - 1, x1 - x0, size[0])):
            if touches and extent >= 0.5 * whole and side not in sides:
                sides.append(side)
    return sides


# ---------- images, the photo ----------

def _read_images(page, number: int, height: float) -> list[dict]:
    return [{"page": number, "bbox": _bbox(obj, height)} for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE])]


def render_box(page, bbox: list[float], scale: float, pad: float = 0.0):
    """The part of *page* in *bbox* (points, origin top left), padded by *pad* and kept inside the page, as a
    PIL image at *scale* pixels per point, with the box the image shows."""
    width, height = page.get_size()
    x0, y0, x1, y1 = max(bbox[0] - pad, 0.0), max(bbox[1] - pad, 0.0), min(bbox[2] + pad, width), min(bbox[3] + pad, height)
    image = page.render(scale=scale, crop=(x0, height - y1, width - x1, y0)).to_pil().convert("RGB")
    return image, [x0, y0, x1, y1]


def _seen(page, bbox: list[float], background: str | None) -> tuple[list[float], str]:
    """What a picture shows of its box: the box of the pixels that differ from what is around it (a picture often
    has a blank margin), and its `shape`: `circle` when the corners of that box show the ground and the middle of
    each side does not, else `rect`."""
    image, shown = render_box(page, bbox, 2.0, pad=3.0)
    scale = image.width / (shown[2] - shown[0])
    around = image.getpixel((0, 0)) if bbox[0] - shown[0] >= 2 and bbox[1] - shown[1] >= 2 else _hex_rgb(background or "#ffffff")
    px = image.load()
    xs, ys = [], []
    for y in range(image.height):
        for x in range(image.width):
            if _distance(px[x, y], around) > 12:
                xs.append(x)
                ys.append(y)
    if not xs:
        return bbox, "rect"
    ink = [min(xs), min(ys), max(xs), max(ys)]
    box = [round(max(bbox[0], shown[0] + ink[0] / scale), 1), round(max(bbox[1], shown[1] + ink[1] / scale), 1),
           round(min(bbox[2], shown[0] + (ink[2] + 1) / scale), 1), round(min(bbox[3], shown[1] + (ink[3] + 1) / scale), 1)]
    mx, my = (ink[0] + ink[2]) // 2, (ink[1] + ink[3]) // 2
    corners = [(ink[0] + 1, ink[1] + 1), (ink[2] - 1, ink[1] + 1), (ink[0] + 1, ink[3] - 1), (ink[2] - 1, ink[3] - 1)]
    sides = [(mx, ink[1] + 1), (mx, ink[3] - 1), (ink[0] + 1, my), (ink[2] - 1, my)]
    round_ = (all(_distance(px[c], around) <= 12 for c in corners) and all(_distance(px[c], around) > 40 for c in sides)
              and _distance(px[mx, my], around) > 40)
    return box, "circle" if round_ else "rect"


def _hex_rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def _distance(a, b) -> int:
    return max(abs(x - y) for x, y in zip(a[:3], b[:3]))


def find_photo(page, images: list[dict], size: list[float], background: str | None) -> dict | None:
    """The photo: the largest picture of page one with both sides at least 40 pt, an aspect between 1:2 and 2:1 and
    under 90% of the page; `circle` when it is cut round, else `rect`."""
    best = None
    for image in images:
        w, h = image["bbox"][2] - image["bbox"][0], image["bbox"][3] - image["bbox"][1]
        if min(w, h) >= 40 and 0.5 <= w / h <= 2 and w * h < 0.9 * size[0] * size[1] and (not best or w * h > best[0]):
            best = (w * h, image)
    if not best:
        return None
    box, shape = _seen(page, best[1]["bbox"], background)
    return {"page": 1, "bbox": box, "shape": shape}


def background_images(images: list[dict], size: list[float]) -> int:
    return sum((i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]) >= 0.9 * size[0] * size[1] for i in images)


# ---------- margins ----------

def _is_footer(run: dict, size: list[float]) -> bool:
    low = run["bbox"][3] > size[1] * 0.94
    return low and (run["text"].strip().isdigit() or bool(_PAGE_FOOTER.fullmatch(run["text"].strip())))


def margins(pages: list[dict]) -> dict:
    """The space between the page edge and the text, the smallest over the pages (to 0.5 pt): a page number or
    `Page N of M` in the foot, rotated text and icons are not counted."""
    out = {"top": [], "right": [], "bottom": [], "left": []}
    for page in pages:
        runs = [r for r in page["runs"] if not r["rotated"] and not r["icon"] and not _is_footer(r, page["size"])]
        if not runs:
            continue
        w, h = page["size"]
        out["left"].append(min(r["bbox"][0] for r in runs))
        out["top"].append(min(r["bbox"][1] for r in runs))
        out["right"].append(w - max(r["bbox"][2] for r in runs))
        out["bottom"].append(h - max(r["bbox"][3] for r in runs))
    return {side: round(min(values) * 2) / 2 if values else 0.0 for side, values in out.items()}


# ---------- columns ----------

def body_size(runs: list[dict]) -> float:
    """The font size most characters are set in."""
    chars: dict[float, int] = {}
    for run in runs:
        chars[run["size"]] = chars.get(run["size"], 0) + len(run["text"])
    return max(chars, key=chars.get) if chars else 10.0


def line_groups(runs: list[dict]) -> list[list[dict]]:
    """The runs as lines: those of a page whose baselines are within 0.3 of their size, left to right."""
    lines: list[list[dict]] = []
    for run in sorted(runs, key=lambda r: (r["page"], r["baseline"], r["bbox"][0])):
        if lines and lines[-1][0]["page"] == run["page"] and abs(lines[-1][0]["baseline"] - run["baseline"]) <= 0.3 * run["size"]:
            lines[-1].append(run)
        else:
            lines.append([run])
    return [sorted(line, key=lambda r: r["bbox"][0]) for line in lines]


def _joined(line: list[dict]) -> str:
    """The text of a line's runs, a space where one run ended or began with one or they are a word apart."""
    out = line[0]["text"]
    for prev, run in zip(line, line[1:]):
        out += (" " if prev["trail"] or run["lead"] or run["bbox"][0] - prev["bbox"][2] > 0.2 * run["size"] else "") + run["text"]
    return out


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(int(q * len(ordered)), len(ordered) - 1)]


def _gaps(runs: list[dict], body: float) -> list[tuple[float, float]]:
    """The empty strips between stacks of text: a place where at most 30% of the busiest x is covered and the runs
    either side of it (at least four each) leave 8 pt or 0.8 body sizes between them, with no more runs across it
    than a third of those on its two sides (a header over both columns does not close it). Each as the clear
    space itself, from the right edge of the runs to its left to the left edge of those to its right."""
    lo, hi = int(min(r["bbox"][0] for r in runs)), int(max(r["bbox"][2] for r in runs)) + 1
    cover = [0] * (hi - lo + 1)
    for run in runs:
        for x in range(int(run["bbox"][0]) - lo, int(run["bbox"][2]) - lo + 1):
            cover[x] += 1
    limit = max(1, 0.3 * max(cover))
    found, start = [], None
    for x, n in enumerate(cover + [limit + 1]):
        if n <= limit and start is None:
            start = x
        elif n > limit and start is not None:
            a, b = lo + start, lo + x
            start = None
            mid = (a + b) / 2
            left = [r for r in runs if r["bbox"][2] <= b and r["bbox"][0] < mid]
            right = [r for r in runs if r["bbox"][0] >= a and r["bbox"][2] > mid]
            across = [r for r in runs if r["bbox"][0] < a and r["bbox"][2] > b]
            if len(left) < 4 or len(right) < 4 or len(across) > (len(left) + len(right)) / 3:
                continue
            clear = (_percentile([r["bbox"][2] for r in left], 0.9), _percentile([r["bbox"][0] for r in right], 0.1))
            if clear[1] - clear[0] >= max(8.0, 0.8 * body):
                found.append(clear)
    return found


def _stacked(lines: list[list[dict]], body: float) -> int:
    """How many lines have another line within two and a half body sizes below or above on the page."""
    count = 0
    for i, line in enumerate(lines):
        near = [o for j in (i - 1, i + 1) if 0 <= j < len(lines) for o in [lines[j]]
                if o[0]["page"] == line[0]["page"] and abs(o[0]["baseline"] - line[0]["baseline"]) <= 2.5 * body]
        count += bool(near)
    return count


def column_bands(pages: list[dict]) -> dict:
    """The column bands of the text: stacks of lines apart by a gap. A band needs four lines that stand together
    (the dates down the right of a single column, or a note in the margin, are no column) and a twelfth of the
    lines. One band is `only`; with more, the narrowest, if under 40% of the text's width or on a coloured box, is
    the `side`, the others `main`. `background` is the fill of a box covering most of the page's height."""
    runs = [r for p in pages for r in p["runs"] if not r["rotated"] and not r["icon"]
            and not (len(r["text"]) <= 1 or all(c in _BULLETS for c in r["text"]))]
    if not runs:
        return {"count": 0, "bands": []}
    body = body_size(runs)
    gaps = sorted(_gaps(runs, body))
    members: list[list[dict]] = [[] for _ in range(len(gaps) + 1)]
    for run in runs:
        if any(run["bbox"][0] < a and run["bbox"][2] > b for a, b in gaps):
            continue  # a run across a gap is a banner: no band's
        members[sum(run["bbox"][0] >= (a + b) / 2 for a, b in gaps)].append(run)
    total = sum(len(line_groups(m)) for m in members) or 1
    bands = []
    for member in members:
        lines = line_groups(member)
        if member and _stacked(lines, body) >= 4 and len(lines) >= total / 12:
            bands.append({"x0": round(_percentile([r["bbox"][0] for r in member], 0.05), 1),
                          "x1": round(_percentile([r["bbox"][2] for r in member], 0.95), 1),
                          "lines": len(lines)})
    if not bands:
        bands = [{"x0": round(min(r["bbox"][0] for r in runs), 1), "x1": round(max(r["bbox"][2] for r in runs), 1),
                  "lines": len(line_groups(runs))}]
    height = pages[0]["size"][1]
    boxes = [s for p in pages for s in p["shapes"] if s["kind"] == "box" and s["fill"]
             and s["bbox"][3] - s["bbox"][1] >= 0.8 * height]

    def box_under(band: dict) -> dict | None:
        mid = (band["x0"] + band["x1"]) / 2
        return next((b for b in boxes if b["bbox"][0] - 1 <= mid <= b["bbox"][2] + 1), None)

    width = max(b["x1"] for b in bands) - min(b["x0"] for b in bands)
    narrowest = min(bands, key=lambda b: b["x1"] - b["x0"])
    for band in bands:
        box = box_under(band)
        band["background"] = box["fill"] if box else None
        side = band is narrowest and len(bands) > 1 and (band["x1"] - band["x0"] < 0.4 * width or box)
        band["kind"] = "only" if len(bands) == 1 else "side" if side else "main"
    return {"count": len(bands), "bands": [{k: b[k] for k in ("x0", "x1", "kind", "background", "lines")} for b in bands]}


# ---------- name, headings, colours ----------

_SECTION_KINDS = tuple(i18n.CvSections.model_fields)


def _case(text: str) -> str:
    return "upper" if text.isupper() else "title" if text.istitle() else "as_written"


def _line_units(runs: list[dict]) -> list[dict]:
    """The lines whose runs share a font family, weight and colour, each as one piece of text: small capitals are
    written as a large letter then smaller ones, so a heading or a name is often several runs. `size` is the
    largest of them, `mixed` whether they differ."""
    units = []
    pieces = []
    for line in line_groups([r for r in runs if not r["rotated"] and not r["icon"]]):
        piece = [line[0]]
        for run in line[1:]:  # a gap wider than a word or two starts another piece: a column's, or a date's
            if run["bbox"][0] - piece[-1]["bbox"][2] > 1.2 * run["size"]:
                pieces.append(piece)
                piece = []
            piece.append(run)
        pieces.append(piece)
    for line in pieces:
        if len({(r["family"], r["weight"], r["color"]) for r in line}) != 1:
            continue
        first = line[0]
        units.append({"page": first["page"], "text": _joined(line), "size": max(r["size"] for r in line),
                      "mixed": len({r["size"] for r in line}) > 1, "color": first["color"], "weight": first["weight"],
                      "family": first["family"],
                      "bbox": [min(r["bbox"][0] for r in line), min(r["bbox"][1] for r in line),
                               max(r["bbox"][2] for r in line), max(r["bbox"][3] for r in line)]})
    return units


def find_name(runs: list[dict]) -> dict | None:
    """The largest text of the first page, the whole line of it: the candidate's name."""
    units = [u for u in _line_units(runs) if u["page"] == 1]
    if not units:
        return None
    unit = max(units, key=lambda u: (u["size"], -u["bbox"][1]))
    return {k: unit[k] for k in ("text", "size", "color", "family")}


def _rule_under(heading: dict, shapes: list[dict], band: dict | None) -> dict | None:
    """The rule or dashed line 0 to 10 pt under a heading that starts where it starts and runs under at least half
    of it; `span` is `column` when it runs the width of the heading's column, else `text`."""
    x0, _, x1, bottom = heading["bbox"]
    for shape in shapes:
        if shape["page"] != heading["page"] or shape["kind"] not in ("rule", "dash"):
            continue
        sx0, sy0, sx1, sy1 = shape["bbox"]
        gap = sy0 - bottom
        overlap = min(x1, sx1) - max(x0, sx0)
        if sx1 - sx0 > sy1 - sy0 and -1 <= gap <= 10 and abs(sx0 - x0) <= 6 and overlap >= 0.5 * (x1 - x0):
            wide = band and sx1 - sx0 >= 0.9 * (band["x1"] - band["x0"])
            return {"color": shape["fill"] or shape["stroke"], "width": shape["width"], "gap": round(max(gap, 0), 1),
                    "x0": sx0, "x1": sx1, "span": "column" if wide else "text"}
    return None


def find_headings(runs: list[dict], shapes: list[dict], bands: list[dict], name: dict | None) -> list[dict]:
    """The section headings: a short line in one style, not set like the body text (another size, weight or family,
    or in small capitals), that is a known section name (any supported language) or one of a group of three or more
    lines in one style that is coloured and larger than the body (or, with no such group, the largest)."""
    body = body_size([r for r in runs if not r["rotated"]])
    chars: dict[tuple, int] = {}
    for r in runs:
        chars[(r["family"], r["size"], r["weight"])] = chars.get((r["family"], r["size"], r["weight"]), 0) + len(r["text"])
    body_style = max(chars, key=chars.get) if chars else None
    short = [u for u in _line_units(runs) if len(u["text"].split()) <= 6
             and not (name and u["text"] == name["text"] and u["size"] == name["size"])
             and (u["mixed"] or (u["family"], u["size"], u["weight"]) != body_style)]

    def key(u: dict) -> tuple:
        return (u["family"], u["size"], u["color"], u["weight"], u["mixed"])

    known = {id(u) for u in short if i18n.cv_section_kind(u["text"], _SECTION_KINDS) is not None}
    text_color = max({r["color"] for r in runs}, key=lambda c: sum(len(r["text"]) for r in runs if r["color"] == c))
    groups: dict[tuple, list[dict]] = {}
    for u in short:
        groups.setdefault(key(u), []).append(u)
    # a group of three or more like lines is headings when it holds a section name or is coloured and larger than the
    # body; with neither anywhere, the largest group is (the entry titles of a CV are in a group of their own)
    styled = {k: g for k, g in groups.items() if len(g) >= 3 and k[1] >= body}
    chosen = [k for k, g in styled.items() if any(id(u) in known for u in g)
              or (k[2] != text_color and _chromatic(k[2]) and k[1] > body)]
    if not chosen and styled:
        chosen = [max(styled, key=lambda k: k[1])]
    found = []
    for u in short:
        if id(u) in known or key(u) in chosen:
            mid = (u["bbox"][0] + u["bbox"][2]) / 2
            band = next((b for b in bands if b["x0"] - 2 <= mid <= b["x1"] + 2), None)
            found.append({"page": u["page"], "text": u["text"], "bbox": u["bbox"], "size": u["size"], "color": u["color"],
                          "weight": u["weight"], "family": u["family"], "case": _case(u["text"]),
                          "rule": _rule_under(u, shapes, band)})
    return found


def heading_style(headings: list[dict]) -> dict | None:
    """What most headings share: size, colour, weight, family, case and (if most have one) their rule."""
    if not headings:
        return None
    keys = ("size", "color", "weight", "family", "case")
    best = max({tuple(h[k] for k in keys) for h in headings}, key=lambda t: sum(tuple(h[k] for k in keys) == t for h in headings))
    same = [h for h in headings if tuple(h[k] for k in keys) == best]
    ruled = [h["rule"] for h in same if h["rule"]]
    rule = None
    if len(ruled) * 2 > len(same):
        def sig(r: dict) -> tuple:
            return (r["color"], r["width"], r["gap"], r["span"])

        top = max(ruled, key=lambda r: sum(sig(o) == sig(r) for o in ruled))
        rule = {k: top[k] for k in ("color", "width", "gap", "span")}
    return {**dict(zip(keys, best)), "rule": rule}


def _chromatic(color: str) -> bool:
    channels = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return max(channels) - min(channels) > 40


def colors(runs: list[dict], shapes: list[dict]) -> dict:
    """The colours of the text (the one most characters have) and of drawn fills, and the accent: the strongest
    colour (characters, plus the area of fills at one character to 70 pt2) that is not grey and not the text's."""
    palette: dict[str, dict] = {}
    for r in runs:
        entry = palette.setdefault(r["color"], {"color": r["color"], "chars": 0, "area": 0.0})
        entry["chars"] += sum(not c.isspace() for c in r["text"])
    for s in shapes:
        if s["fill"] and s["kind"] in ("box", "dot", "rule"):
            entry = palette.setdefault(s["fill"], {"color": s["fill"], "chars": 0, "area": 0.0})
            entry["area"] = round(entry["area"] + (s["bbox"][2] - s["bbox"][0]) * (s["bbox"][3] - s["bbox"][1]), 1)
    ranked = sorted(palette.values(), key=lambda e: -(e["chars"] + e["area"] / 70))
    text = max(palette.values(), key=lambda e: e["chars"])["color"] if palette else None
    accent = next((e["color"] for e in ranked if e["color"] != text and _chromatic(e["color"])), None)
    return {"text": text, "accent": accent, "palette": ranked}


# ---------- nothing to copy ----------

_NOT_PDF = {".docx", ".doc", ".odt", ".rtf", ".txt", ".md", ".html", ".htm"}
_LINKEDIN_HEADINGS = {"contact", "top skills", "languages", "certifications", "summary", "experience", "education"}
_PAGE_FOOTER = re.compile(r"page \d+ of \d+", re.I)
_MIN_CHARS = 50


def not_pdf(path) -> dict | None:
    """The verdict for a file that is not a PDF (a Word file, plain text: no layout to copy), by its suffix;
    None for a PDF, which `extract` judges by what is in it. Called where the file is taken in."""
    suffix = Path(path).suffix.lower()
    if suffix not in _NOT_PDF:
        return None
    return {"copyable": False, "reason": "not_pdf", "detail": f"a {suffix[1:]} file has no layout to copy"}


def style_verdict(pages: list[dict]) -> dict:
    """Whether there is a style to copy: a scan (under 50 visible characters: no text layer, or an invisible OCR
    layer) or a LinkedIn export (at least three of its section headings as lines of their own and a `Page N of M`
    line on every page; English only) has not. Anything else, a plain single-font CV included, is copyable."""
    chars = sum(len(r["text"].replace(" ", "")) for p in pages for r in p["runs"])
    if chars < _MIN_CHARS:
        return _verdict(False, "scan", f"{chars} visible characters: no text layer to read")
    lines = [{r["text"].casefold().strip() for r in p["runs"]} for p in pages]
    headings = set().union(*lines) & _LINKEDIN_HEADINGS
    footers = all(any(_PAGE_FOOTER.fullmatch(t) for t in page) for page in lines)
    if len(headings) >= 3 and footers:
        return _verdict(False, "linkedin", "the sections and page footers of a LinkedIn export, which has no design")
    return _verdict(True, "ok", "")


def _verdict(copyable: bool, reason: str, detail: str) -> dict:
    return {"copyable": copyable, "reason": reason, "detail": detail}


# ---------- icons ----------

_ICON_FONT = re.compile(r"awesome|icon|symbol|material|glyph|fontello|ionicons|dingbats|wingdings", re.I)
_ICON_SIZE = 24.0  # points: a drawing larger than this is not an icon
_SCALE = 10.0  # pixels per point an icon is traced at


def _glyph_only(text: str) -> bool:
    """Only control characters, private use or dingbats: what an icon font's glyphs read as."""
    return all(c < " " or "\ue000" <= c <= "\uf8ff" or "\u2700" <= c <= "\u27bf" for c in text)


def mark_icon_runs(runs: list[dict]) -> None:
    """Set `icon` on the runs that are glyphs of an icon font (FontAwesome and the like): a font named like one, a
    run of only private-use or control characters, or a font whose runs are all a character or two of symbols.
    A bullet is no icon."""
    short = {}
    for run in runs:
        short[run["font"]] = short.get(run["font"], True) and len(run["text"]) <= 2 and not run["text"].isalnum()
    for run in runs:
        if all(c in _BULLETS for c in run["text"]):
            continue
        run["icon"] = bool(_ICON_FONT.search(run["font"]) or _glyph_only(run["text"]) or short[run["font"]])


def _touching(a: list[float], b: list[float]) -> bool:
    return a[0] <= b[2] + 1 and b[0] <= a[2] + 1 and a[1] <= b[3] + 1 and b[1] <= a[3] + 1


def _vector_icons(shapes: list[dict]) -> list[tuple[list[float], str]]:
    """Small drawings that are no rule, dot or box (four segments or more), those that touch put together: each
    as (box, colour)."""
    groups: list[dict] = []
    for shape in shapes:
        x0, y0, x1, y1 = shape["bbox"]
        if shape["kind"] or len(shape["segments"]) < 4 or x1 - x0 > _ICON_SIZE or y1 - y0 > _ICON_SIZE:
            continue
        near = [g for g in groups if _touching(g["bbox"], shape["bbox"])]
        merged = {"bbox": shape["bbox"], "color": shape["fill"] or shape["stroke"]}
        for g in near:
            groups.remove(g)
            merged["bbox"] = [min(merged["bbox"][0], g["bbox"][0]), min(merged["bbox"][1], g["bbox"][1]),
                              max(merged["bbox"][2], g["bbox"][2]), max(merged["bbox"][3], g["bbox"][3])]
        groups.append(merged)
    return [(g["bbox"], g["color"]) for g in groups
            if g["bbox"][2] - g["bbox"][0] <= _ICON_SIZE and g["bbox"][3] - g["bbox"][1] <= _ICON_SIZE]


def _near(box: list[float], runs: list[dict]) -> dict | None:
    """The text an icon belongs to: the nearest run on its line, to its right first, else to its left."""
    mid = (box[1] + box[3]) / 2
    line = [r for r in runs if not r["icon"] and not r["rotated"] and r["bbox"][1] - 0.5 * r["size"] <= mid <= r["bbox"][3] + 0.5 * r["size"]]
    right = sorted((r for r in line if r["bbox"][0] >= box[2] - 1), key=lambda r: r["bbox"][0] - box[2])
    left = sorted((r for r in line if r["bbox"][2] <= box[0] + 1), key=lambda r: box[0] - r["bbox"][2])
    for side, found in (("right", right), ("left", left)):
        if found:
            return {"text": found[0]["text"], "side": side}
    return None


def _ink_color(image) -> str:
    ground = image.getpixel((0, 0))
    best = max(((_distance(image.getpixel((x, y)), ground), (x, y)) for x in range(image.width) for y in range(image.height)))
    return "#%02x%02x%02x" % image.getpixel(best[1])


def _icon(page, number: int, box: list[float], color: str | None, source: str, font: str | None, runs: list[dict]) -> dict | None:
    image, shown = render_box(page, box, _SCALE, pad=1.0)
    scale = image.width / (shown[2] - shown[0])
    traced = style_trace.trace(image, scale, color or "#000000")
    if not traced:
        return None
    if color is None:
        traced["fill"] = _ink_color(image.crop(tuple(traced["bbox"])))
    px = traced.pop("bbox")
    bbox = [round(shown[0] + px[0] / scale, 1), round(shown[1] + px[1] / scale, 1),
            round(shown[0] + px[2] / scale, 1), round(shown[1] + px[3] / scale, 1)]
    return {"page": number, "bbox": bbox, "source": source, "font": font, "color": traced.pop("fill"), "viewBox": traced["viewBox"],
            "d": traced["d"], "fill_rule": traced["fill_rule"], "near": _near(bbox, runs)}


def find_icons(doc, pages: list[dict]) -> list[dict]:
    """Icons as SVG paths: glyphs of icon fonts, small drawings and small pictures, each traced from a large
    render of its box (`style_trace`), with the text it is next to."""
    icons = []
    for number, (page, data) in enumerate(zip(doc, pages), 1):
        found = [(r["bbox"], r["color"], "font", r["font"]) for r in data["runs"] if r["icon"]]
        found += [(box, color, "vector", None) for box, color in _vector_icons([s for s in data["shapes"] if s["segments"]])]
        for image in data["images"]:
            w, h = image["bbox"][2] - image["bbox"][0], image["bbox"][3] - image["bbox"][1]
            if image["bbox"] != (data["photo"] or {}).get("bbox") and 3 <= min(w, h) and max(w, h) <= 48 and 0.5 <= w / h <= 2:
                found.append((image["bbox"], None, "image", None))
        for box, color, source, font in found:
            icon = _icon(page, number, box, color, source, font, data["runs"])
            if icon:
                icons.append(icon)
    return sorted(icons, key=lambda i: (i["page"], i["bbox"][1], i["bbox"][0]))


# ---------- the whole read ----------

def _fonts_used(runs: list[dict]) -> list[dict]:
    fonts: dict[str, dict] = {}
    keys = ("font", "family", "weight", "italic", "serif", "fixed", "embedded")
    for run in runs:
        entry = fonts.setdefault(run["font"], {**{k: run[k] for k in keys}, "runs": 0, "chars": 0})
        entry["runs"] += 1
        entry["chars"] += sum(not c.isspace() for c in run["text"])
    return sorted(fonts.values(), key=lambda f: -f["chars"])


def _read_pages(doc) -> list[dict]:
    """Per page: size, merged text runs, drawn shapes (the page background taken out), images and the photo."""
    pages = []
    for number, page in enumerate(doc, 1):
        width, height = page.get_size()
        runs = _text_runs(page, number, height)
        size = [round(width, 1), round(height, 1)]
        background, shapes = _page_background(_read_shapes(page, number, height), size)
        images = _read_images(page, number, height)
        photo = find_photo(page, images, size, background) if number == 1 else None
        pages.append({"size": size, "runs": merge_runs(runs), "shapes": shapes, "background": background,
                      "images": images, "photo": photo})
    return pages


def extract(pdf_path: Path) -> dict:
    """The style of the CV in *pdf_path* (see the module's docstring). Raises FileNotFoundError for a missing
    file and pypdfium2's PdfiumError for one that is not a PDF."""
    doc = pdf_render._open(pdf_path)
    try:
        pages = _read_pages(doc)
        head = {"version": VERSION, "verdict": style_verdict(pages), "producer": doc.get_metadata_value("Producer"),
                "creator": doc.get_metadata_value("Creator"), "page_count": len(doc)}
        if not head["verdict"]["copyable"]:
            return head
        mark_icon_runs([r for p in pages for r in p["runs"]])
        runs = [r for p in pages for r in p["runs"]]
        shapes = [s for p in pages for s in p["shapes"] if s["kind"]]
        page = {"size": pages[0]["size"], "background": pages[0]["background"], "margins": margins(pages),
                "bleed": _bleed(shapes, pages[0]["size"])}
        columns = column_bands([{**p, "shapes": [s for s in p["shapes"] if s["kind"]]} for p in pages])
        name = find_name(runs)
        headings = find_headings(runs, shapes, columns["bands"], name)
        return {**head, "page": page, "fonts": _fonts_used(runs), "colors": colors(runs, shapes), "name": name,
                "columns": columns, "headings": headings, "heading_style": heading_style(headings),
                "runs": [{k: v for k, v in r.items() if k not in _INTERNAL} for r in runs],
                "shapes": [{k: v for k, v in s.items() if k != "segments"} for s in shapes],
                "icons": find_icons(doc, pages), "photo": pages[0]["photo"],
                "background_images": sum(background_images(p["images"], p["size"]) for p in pages)}
    finally:
        doc.close()
