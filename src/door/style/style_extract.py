"""Read a CV PDF's style as facts (#148, epic #144): fonts, sizes, colours, margins, columns, headings, drawn
shapes, icons as SVG paths, the photo. Pure and offline: pypdfium2 and Pillow, nothing written, no network.

`extract(pdf_path, structure=None)` returns one dict (schema version 1, points, the origin at the top left, colours
`#rrggbb`): `verdict` first (`scan_verdict` says a scan has nothing to copy; the `structure`, the CV's name, headings and
columns as `style_structure` read them with one model call (#343), says a LinkedIn export has none and a page of
three columns, which the template cannot place, refuses with every other key still there), then `runs` (one per piece of text on a line), `fonts`, `page` (size, margins, bleed,
background), `colors` (text, accent), `name`, `columns` (bands), `headings` and `heading_style`, `shapes`, `icons`
(SVG paths next to the text they belong to), `photo`. Fonts are only described (family, weight, italic, serif, fixed); looking
them up is another step. Icons are `style_icons`'s, traced by `style_trace`.
"""

from __future__ import annotations

import ctypes
import math
import re
from pathlib import Path

import pypdfium2.raw as raw

from door.render import pdf_render
from door.style import style_icons, style_trace

VERSION = 1
_INTERNAL = {"baseline", "lead", "trail", "parts", "gaps"}  # what the analysis keeps on a run and the result does not

# fonts
_WEIGHTS = [  # longest names first: "extrabold" holds "bold"
    ("extrablack", 900), ("ultrablack", 900), ("extralight", 200), ("ultralight", 200), ("extrabold", 800),
    ("ultrabold", 800), ("semibold", 600), ("demibold", 600), ("hairline", 100), ("regular", 400),
    ("medium", 500), ("normal", 400), ("light", 300), ("heavy", 800), ("black", 900), ("bold", 700),
    ("thin", 100), ("book", 400),
]
_STYLE_WORDS = {w for w, _ in _WEIGHTS} | {"italic", "oblique", "roman", "ital", "it"}
_SANS_NAMES = re.compile(r"sans|sanl|heros|helvet|arial|lato|figtree|optima|calibri|verdana|tahoma|roboto|segoe|gothic|avenir|"
                         r"futura|montserrat|raleway|poppins|nunito|ubuntu|carlito|arimo|\binter\b", re.I)
_SERIF_NAMES = re.compile(r"times|georgia|garamond|palatino|palladio|cambria|minion|baskerville|bookman|caslon|didot|roman|"
                          r"charter|tinos|caladea|lora|merriweather|playfair|crimson|serif", re.I)
_FIXED_NAMES = re.compile(r"courier|mono|consolas|typewriter|menlo", re.I)
_FLAG_FIXED, _FLAG_SERIF, _FLAG_ITALIC, _FLAG_FORCE_BOLD = 0x1, 0x2, 0x40, 0x40000

# shapes
_RULE_MAX, _RULE_MIN_LENGTH, _DOT_MAX = 3.5, 20.0, 10.0

# nothing to copy
PAGE_FOOTER = re.compile(r"page \d+ of \d+", re.I)
_MIN_CHARS = 50


# ---------- fonts ----------

def font_facts_from_name(name: str) -> dict:
    """Family, weight and italic as a font's base name tells them (`ABCDEF+Lato-Light`, `Arial-BoldMT`)."""
    base = name.split("+", 1)[-1]
    parts = re.split(r"[-,]", base, maxsplit=1)
    family, style = parts[0], (parts[1] if len(parts) > 1 else "")
    family = re.sub(r"(MT|PS)$", "", family).strip()
    lowered = style.lower().replace(" ", "")
    weight = next((w for word, w in _WEIGHTS if word in lowered), 400)
    return {"family": family, "weight": weight, "italic": "italic" in lowered or "oblique" in lowered}


def is_serif(name: str, flags: int) -> bool:
    """Whether a font has serifs: its name says (sans first, then serif), and only a name that says nothing leaves
    it to the descriptor's flag, which tools set loosely (pdfTeX the serif bit on a sans font, Chromium never)."""
    if _SANS_NAMES.search(name):
        return False
    return bool(_SERIF_NAMES.search(name)) or bool(flags & _FLAG_SERIF)


def font_facts(name: str, flags: int, italic_angle: int, family: str) -> dict:
    """What is known of a font: from its base name, the descriptor's flags and italic angle, and the family it
    declares (only an embedded font's is trusted: pdfium names a stand-in for the others)."""
    facts = font_facts_from_name(name)
    if family and not any(w in family.lower().split() for w in _STYLE_WORDS):
        facts["family"] = family
    if flags & _FLAG_FORCE_BOLD:
        facts["weight"] = max(facts["weight"], 700)
    facts["italic"] = facts["italic"] or bool(flags & _FLAG_ITALIC) or bool(italic_angle)
    return {"font": name, **facts, "serif": is_serif(name, flags),
            "fixed": bool(flags & _FLAG_FIXED) or bool(_FIXED_NAMES.search(name))}


def _font_facts(font) -> dict:
    embedded = bool(raw.FPDFFont_GetIsEmbedded(font.raw))
    angle = ctypes.c_int()
    raw.FPDFFont_GetItalicAngle(font.raw, angle)
    facts = font_facts(font.get_base_name().split("+", 1)[-1], raw.FPDFFont_GetFlags(font.raw), angle.value,
                       font.get_family_name() if embedded else "")
    return {**facts, "embedded": embedded}


def name_nameless(runs: list[dict], anchors: list[dict]) -> None:
    """Chromium writes a font it cannot name (a variable one, some static ones) as glyph objects with no font name,
    but the space after a word in the same font keeps it: a nameless run takes the facts of the named space on its
    baseline; with none there it is marked `type3` and left unnamed."""
    for run in runs:
        if run["font"]:
            continue
        near = [a for a in anchors if a["page"] == run["page"] and abs(a["baseline"] - run["baseline"]) <= 0.3 * run["size"]]
        if near:
            best = min(near, key=lambda a: abs(a["baseline"] - run["baseline"]))
            run.update({k: best[k] for k in ("font", "family", "weight", "italic", "serif", "fixed")})
        else:
            run["type3"] = True


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
    runs, anchors = [], []
    try:
        for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT]):
            if raw.FPDFTextObj_GetTextRenderMode(obj.raw) == 3:
                continue
            obj.textpage = textpage
            raw_text = obj.extract()
            text = raw_text.strip()
            m = obj.get_matrix()
            size = round(obj.get_font_size() * math.hypot(m.c, m.d), 1)
            facts = _font_facts(obj.get_font())
            baseline = round(height - m.f, 1)
            if not text:
                if facts["font"]:  # an empty or space-only object in a named font: it names the nameless glyphs beside it
                    anchors.append({"page": number, "baseline": baseline, **facts})
                continue
            runs.append({"page": number, "text": text, "bbox": _bbox(obj, height), "size": size,
                         "color": _rgb(raw.FPDFPageObj_GetFillColor, obj), "rotated": abs(m.b) > abs(m.a),
                         "baseline": baseline, "type3": False,
                         "lead": raw_text[:1].isspace(), "trail": raw_text[-1:].isspace(), **facts})
    finally:
        textpage.close()
    name_nameless(runs, anchors)
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


def _round(segs) -> bool:
    """Whether the points a path passes through lie on a circle around the middle of its box."""
    on_curve, bezier = [], 0
    for kind, x, y, _ in segs:
        bezier = bezier + 1 if kind == raw.FPDF_SEGMENT_BEZIERTO else 0
        if kind != raw.FPDF_SEGMENT_BEZIERTO or bezier % 3 == 0:
            on_curve.append((x, y))
    cx, cy = (min(x for x, _ in on_curve) + max(x for x, _ in on_curve)) / 2, (min(y for _, y in on_curve) + max(y for _, y in on_curve)) / 2
    radii = [math.hypot(x - cx, y - cy) for x, y in on_curve]
    return min(radii) > 0 and max(radii) / min(radii) <= 1.2


def _shape_kind(segs, width: float, height: float, filled: bool, stroke_width: float, stroked: bool, dash) -> str | None:
    """The kind of a path from its geometry (`rule`, `dash`, `dot`, `box`), or None for anything else, which is
    left for the icon pass."""
    curves = sum(t == raw.FPDF_SEGMENT_BEZIERTO for t, *_ in segs)
    points = [(x, y) for _, x, y, _ in segs]
    if dash and stroked:
        return "dash"
    if not curves and len(points) <= 3 and stroked and not filled and max(width, height) >= _RULE_MIN_LENGTH \
            and stroke_width <= _RULE_MAX:
        return "rule"
    if filled and not curves and min(width, height) <= _RULE_MAX and max(width, height) >= _RULE_MIN_LENGTH \
            and _axis_aligned(points):
        return "rule"
    if filled and width <= _DOT_MAX and height <= _DOT_MAX and abs(width - height) <= 1 and (curves >= 8 or len(points) >= 8) \
            and _round(segs):
        return "dot"
    if not curves and 4 <= len(points) <= 5 and _axis_aligned(points[:4]):
        return "box"
    lines = [((a[1], a[2]), (b[1], b[2])) for a, b in zip(segs, segs[1:]) if b[0] == raw.FPDF_SEGMENT_LINETO]
    if curves and curves // 3 <= 8 and abs(width - height) <= 1 and not lines:
        return "box"  # a circle, bigger than a dot
    if curves and curves // 3 <= 8 and len(lines) >= 3 and all(abs(a[0] - b[0]) < 0.05 or abs(a[1] - b[1]) < 0.05 for a, b in lines):
        return "box"  # a rectangle with round corners
    return None


def _read_shapes(page, number: int, height: float) -> list[dict]:
    """Every path of a page that paints: its kind (rule, dash, dot, box; None for a drawing, which the icon pass
    takes), colours, stroke width, dash pattern, whether a box has round corners, the segments and a box from the
    points (a stroke's own width not in it)."""
    out = []
    for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_PATH]):
        segs = _segments(obj, height)
        fill, stroke = ctypes.c_int(), ctypes.c_int()
        raw.FPDFPath_GetDrawMode(obj.raw, fill, stroke)
        m = obj.get_matrix()
        stroke_width = ctypes.c_float()
        raw.FPDFPageObj_GetStrokeWidth(obj.raw, stroke_width)
        scale = math.sqrt(abs(m.a * m.d - m.b * m.c)) or 1.0
        xs, ys = [p[1] for p in segs], [p[2] for p in segs]
        bbox = [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]
        width_pt = round(stroke_width.value * scale, 2) if stroke.value else 0.0
        dash = _dash(obj) if stroke.value else None
        kind = _shape_kind(segs, bbox[2] - bbox[0], bbox[3] - bbox[1], bool(fill.value), width_pt, bool(stroke.value), dash)
        thickness = round(min(bbox[2] - bbox[0], bbox[3] - bbox[1]), 2)
        out.append({"page": number, "kind": kind, "bbox": bbox,
                    "fill": _rgb(raw.FPDFPageObj_GetFillColor, obj) if fill.value else None,
                    "stroke": _rgb(raw.FPDFPageObj_GetStrokeColor, obj) if stroke.value else None,
                    "width": width_pt or (thickness if kind == "rule" else 0.0), "dash": dash,
                    "rounded": kind == "box" and any(t == raw.FPDF_SEGMENT_BEZIERTO for t, *_ in segs), "segments": segs})
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

def _clip_bounds(obj, height: float) -> list[float] | None:
    """The box of the clip paths that apply to *obj* (top left origin), None when it is not clipped."""
    clip = raw.FPDFPageObj_GetClipPath(obj.raw)
    xs, ys = [], []
    for i in range(raw.FPDFClipPath_CountPaths(clip) if clip else 0):
        for j in range(max(raw.FPDFClipPath_CountPathSegments(clip, i), 0)):
            seg = raw.FPDFClipPath_GetPathSegment(clip, i, j)
            x, y = ctypes.c_float(), ctypes.c_float()
            if seg and raw.FPDFPathSegment_GetPoint(seg, x, y):
                xs.append(x.value)
                ys.append(height - y.value)
    return [min(xs), min(ys), max(xs), max(ys)] if xs else None


def _read_images(page, number: int, height: float) -> list[dict]:
    """Each picture of a page with the box it shows: its own, cut to its clip path (a cover-fitted picture is drawn
    larger than the shape that clips it)."""
    out = []
    for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE]):
        box, clip = _bbox(obj, height), _clip_bounds(obj, height)
        if clip:
            cut = [max(box[0], clip[0]), max(box[1], clip[1]), min(box[2], clip[2]), min(box[3], clip[3])]
            box = cut if cut[2] > cut[0] and cut[3] > cut[1] else box
        out.append({"page": number, "bbox": box})
    return out


def _seen(page, bbox: list[float], background: str | None) -> tuple[list[float], str]:
    """What a picture shows of its box: the box of the pixels that differ from what is around it (a picture often
    has a blank margin), and its `shape`: `circle` when that box is near square and the corners of it show the
    ground as far as a circle's do (`_corner_clearance`), else `rect`."""
    image, shown = pdf_render.render_box(page, bbox, 2.0, pad=3.0)
    scale = image.width / (shown[2] - shown[0])
    around = image.getpixel((0, 0)) if bbox[0] - shown[0] >= 2 and bbox[1] - shown[1] >= 2 else style_trace.channels(background or "#ffffff")
    px = image.load()
    xs, ys = [], []
    for y in range(image.height):
        for x in range(image.width):
            if style_trace.distance(px[x, y], around) > 12:
                xs.append(x)
                ys.append(y)
    if not xs:
        return bbox, "rect"
    ink = [min(xs), min(ys), max(xs), max(ys)]
    box = [round(max(bbox[0], shown[0] + ink[0] / scale), 1), round(max(bbox[1], shown[1] + ink[1] / scale), 1),
           round(min(bbox[2], shown[0] + (ink[2] + 1) / scale), 1), round(min(bbox[3], shown[1] + (ink[3] + 1) / scale), 1)]
    w, h = ink[2] - ink[0] + 1, ink[3] - ink[1] + 1
    round_ = (_ROUND_ASPECT[0] <= w / h <= _ROUND_ASPECT[1]
              and _corner_clearance(lambda x, y: style_trace.distance(px[x, y], around) > 12, ink) >= _ROUND_CLEARANCE)
    return box, "circle" if round_ else "rect"


# A circle inscribed in its box leaves 1 - 1/sqrt(2) = 0.29 of the half-diagonal clear at each corner; a rounded
# corner of radius r on a side s leaves 0.59 r / s (0.09 at r = 15%, 0.14 at 24%, 0.23 at 40%), a square none.
_ROUND_CLEARANCE = 0.2
_ROUND_ASPECT = (0.85, 1 / 0.85)


def _corner_clearance(inked, box: list[int]) -> float:
    """The part of the half-diagonal of *box* (x0, y0, x1, y1 in pixels) that is clear of ink at its least clear
    corner: `inked(x, y)` is walked from each corner towards the middle."""
    half = min(box[2] - box[0] + 1, box[3] - box[1] + 1) / 2
    least = 1.0
    for cx, dx in ((box[0], 1), (box[2], -1)):
        for cy, dy in ((box[1], 1), (box[3], -1)):
            clear = next((i for i in range(int(half)) if inked(cx + dx * i, cy + dy * i)), half)
            least = min(least, clear / half)
    return least


def find_photo(page, images: list[dict], size: list[float], background: str | None) -> tuple[dict, list[float]] | None:
    """The photo: the largest picture of page one with both sides at least 40 pt, an aspect between 1:2 and 2:1 and
    under 90% of the page; `circle` when it is cut round, else `rect`. With the picture's own box, whose blank
    margin the photo's box leaves out."""
    best = None
    for image in images:
        w, h = image["bbox"][2] - image["bbox"][0], image["bbox"][3] - image["bbox"][1]
        if min(w, h) >= 40 and 0.5 <= w / h <= 2 and w * h < 0.9 * size[0] * size[1] and (not best or w * h > best[0]):
            best = (w * h, image)
    if not best:
        return None
    box, shape = _seen(page, best[1]["bbox"], background)
    return {"page": 1, "bbox": box, "shape": shape}, best[1]["bbox"]


# ---------- margins ----------

def _is_footer(run: dict, size: list[float]) -> bool:
    low = run["bbox"][3] > size[1] * 0.94
    return low and (run["text"].strip().isdigit() or bool(PAGE_FOOTER.fullmatch(run["text"].strip())))


def margins(pages: list[dict]) -> dict:
    """The space between the page edge and the text, the smallest over the pages (to 0.5 pt): a page number or
    `Page N of M` in the foot, rotated text and icons are not counted. The bottom one is read only from a page
    with another after it (a last page ends where its text does); with none, it is the top margin."""
    out = {"top": [], "right": [], "bottom": [], "left": []}
    for i, page in enumerate(pages):
        runs = [r for r in page["runs"] if not r["rotated"] and not r["icon"] and not _is_footer(r, page["size"])]
        if not runs:
            continue
        w, h = page["size"]
        out["left"].append(min(r["bbox"][0] for r in runs))
        out["top"].append(min(r["bbox"][1] for r in runs))
        out["right"].append(w - max(r["bbox"][2] for r in runs))
        if i < len(pages) - 1:
            out["bottom"].append(h - max(r["bbox"][3] for r in runs))
    found = {side: round(min(values) * 2) / 2 if values else 0.0 for side, values in out.items()}
    return {**found, "bottom": found["bottom"] if out["bottom"] else found["top"]}


# ---------- lines ----------

def line_groups(runs: list[dict]) -> list[list[dict]]:
    """The runs as lines: those of a page whose baselines are within 0.3 of their size, left to right."""
    lines: list[list[dict]] = []
    for run in sorted(runs, key=lambda r: (r["page"], r["baseline"], r["bbox"][0])):
        if lines and lines[-1][0]["page"] == run["page"] and abs(lines[-1][0]["baseline"] - run["baseline"]) <= 0.3 * run["size"]:
            lines[-1].append(run)
        else:
            lines.append([run])
    return [sorted(line, key=lambda r: r["bbox"][0]) for line in lines]


def joined(line: list[dict]) -> str:
    """The text of a line's runs, a space where one run ended or began with one or they are a word apart."""
    out = line[0]["text"]
    for prev, run in zip(line, line[1:]):
        out += (" " if prev["trail"] or run["lead"] or run["bbox"][0] - prev["bbox"][2] > 0.2 * run["size"] else "") + run["text"]
    return out


# ---------- name, headings, colours ----------

def _case(text: str) -> str:
    return "upper" if text.isupper() else "title" if text.istitle() else "as_written"


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


def heading_style(headings: list[dict]) -> dict | None:
    """What most headings share: size, colour, weight, family, case, italic and (if most have one) their rule; on a tie
    the main column's look over a side band's."""
    if not headings:
        return None
    keys = ("size", "color", "weight", "family", "case", "italic")
    styles = [tuple(h[k] for k in keys) for h in headings]
    # on a tie the style with more headings outside a side band wins (a band's headings are set for its background),
    # then the style met first in reading order, never a hash order
    best = max(dict.fromkeys(styles), key=lambda t: (styles.count(t),
                                                     sum(s == t and h["band"] != "side" for s, h in zip(styles, headings))))
    same = [h for h in headings if tuple(h[k] for k in keys) == best]
    ruled = [h["rule"] for h in same if h["rule"]]
    rule = None
    if len(ruled) * 2 > len(same):
        def sig(r: dict) -> tuple:
            return (r["color"], r["width"], r["gap"], r["span"])

        top = max(ruled, key=lambda r: sum(sig(o) == sig(r) for o in ruled))  # a tie: the first rule met
        rule = {k: top[k] for k in ("color", "width", "gap", "span")}
    return {**dict(zip(keys, best)), "rule": rule}


def _chromatic(color: str) -> bool:
    channels = style_trace.channels(color)
    return max(channels) - min(channels) > 40


def colors(runs: list[dict], shapes: list[dict]) -> dict:
    """The colours of the text (the one most characters have) and of drawn fills, and the accent: the strongest
    colour (characters, plus the area of fills at one character to 70 pt2; both counted per colour) that is not grey and not the text's."""
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
    return {"text": text, "accent": accent}


# ---------- nothing to copy ----------



def not_pdf(path) -> dict | None:
    """The verdict for a file that is not a PDF (a Word file, plain text, a picture: no layout to copy), by its
    suffix; None for a PDF, which `extract` judges by what is in it. Called where the file is taken in. A refusal's
    `detail` is the user's sentence after the file's name (`<name> <detail>`, #273)."""
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return None
    return {"copyable": False, "reason": "not_pdf", "detail": "is not a PDF, so it has no layout to copy."}


def scan_verdict(pages: list[dict]) -> dict:
    """Whether there is text to copy a style from: under 50 visible characters is a scan (no text layer, or an
    invisible OCR layer), which has none. Anything else is copyable."""
    chars = sum(len(r["text"].replace(" ", "")) for p in pages for r in p["runs"])
    if chars < _MIN_CHARS:
        return _verdict(False, "scan", "looks like a scan: there is no text in it to copy the style from.")
    return _verdict(True, "ok", "")


def structure_verdict(structure: dict) -> dict:
    """The verdict of a CV's checked structure (`style_structure.check`): a LinkedIn export has no design of its own and
    three or more columns have no place in the template model (`layout`). Anything else is copyable."""
    if structure["linkedin"]:
        return _verdict(False, "linkedin", "is a LinkedIn export, which has no design of its own to copy.")
    if structure["columns"] == "three":
        return _verdict(False, "layout", "has three or more columns, which the template model cannot place.")
    return _verdict(True, "ok", "")


def _verdict(copyable: bool, reason: str, detail: str) -> dict:
    return {"copyable": copyable, "reason": reason, "detail": detail}


# ---------- the whole read ----------

def _fonts_used(runs: list[dict]) -> list[dict]:
    """Each font of the runs with its use. A font is an icon font when every run of it is an icon or a bullet (a level
    dot drawn from an icon font is no reason to fetch it) and it is named like an icon font or has a real icon
    run."""
    keys = ("font", "family", "weight", "italic", "serif", "fixed", "embedded", "type3")
    by_font: dict[str, list[dict]] = {}
    for run in runs:
        by_font.setdefault(run["font"], []).append(run)
    fonts = []
    for name, its in by_font.items():
        icon = (all(r["icon"] or style_icons.only_bullets(r["text"]) for r in its)
                and (style_icons.icon_font(name) or any(r["icon"] for r in its)))
        fonts.append({**{k: its[0][k] for k in keys}, "icon": icon, "runs": len(its),
                      "chars": sum(not c.isspace() for r in its for c in r["text"])})
    return sorted(fonts, key=lambda f: -f["chars"])


def fonts_used(pages: list[dict]) -> list[dict]:
    """Each font of the pages' text (`read_pages`) with its use, most characters first, as `extract` gives them."""
    return _fonts_used([r for p in pages for r in p["runs"]])


def _read_pages(doc) -> list[dict]:
    """Per page: size, merged text runs, the drawn shapes (the page background taken out) and the drawings left for
    the icon pass, the images, the photo and the box of its picture."""
    pages = []
    for number, page in enumerate(doc, 1):
        width, height = page.get_size()
        size = [round(width, 1), round(height, 1)]
        background, paths = _page_background(_read_shapes(page, number, height), size)
        images = _read_images(page, number, height)
        found = find_photo(page, images, size, background) if number == 1 else None
        pages.append({"size": size, "runs": merge_runs(_text_runs(page, number, height)), "background": background,
                      "shapes": [{k: v for k, v in s.items() if k != "segments"} for s in paths if s["kind"]],
                      "drawings": [s for s in paths if not s["kind"]], "images": images,
                      "photo": found[0] if found else None, "photo_box": found[1] if found else None})
    return pages


def read_pages(pdf_path: Path) -> list[dict]:
    """The pages of the PDF as `_read_pages` reads them, their icon runs marked (`style_icons.mark_icon_runs`)."""
    doc = pdf_render.open_pdf(pdf_path)
    try:
        pages = _read_pages(doc)
    finally:
        doc.close()
    style_icons.mark_icon_runs([r for p in pages for r in p["runs"]])
    return pages


def painted(pdf_path: Path) -> list[dict]:
    """Per page of *pdf_path*, everything drawn: ``{"background", "paths"}``, the page's background fill and every
    path that paints with its kind, box, fill and stroke (a round or rounded box is a path of no kind, which
    `extract` keeps out of its shapes), whatever the verdict."""
    doc = pdf_render.open_pdf(pdf_path)
    try:
        out = []
        for number, page in enumerate(doc, 1):
            width, height = page.get_size()
            background, paths = _page_background(_read_shapes(page, number, height), [width, height])
            out.append({"background": background,
                        "paths": [{k: v for k, v in s.items() if k != "segments"} for s in paths]})
        return out
    finally:
        doc.close()


def _background_under(shapes: list[dict], height: float):
    """A function giving the fill of the box that covers most of the page's height under a band (its middle within
    the box), or None."""
    boxes = [sh for sh in shapes if sh["kind"] == "box" and sh["fill"] and sh["bbox"][3] - sh["bbox"][1] >= 0.8 * height]

    def under(x0: float, x1: float) -> str | None:
        mid = (x0 + x1) / 2
        return next((b["fill"] for b in boxes if b["bbox"][0] - 1 <= mid <= b["bbox"][2] + 1), None)

    return under


def _structure_bands(structure: dict, runs: list[dict], shapes: list[dict], height: float) -> dict:
    """The column bands of the model's layout (`style_structure.check`): one `only` band over the text, or a `side`
    band at the side range and a `main` band over the text that is not in it, left to right, each with the fill of
    the box under it. Three columns have no bands (the layout verdict refuses them)."""
    runs = [r for r in runs if not r["rotated"] and not r["icon"]]
    if structure["columns"] == "three" or not runs:
        return {"count": 3 if structure["columns"] == "three" else 0, "bands": []}
    under = _background_under(shapes, height)
    if structure["columns"] == "one":
        parts = [("only", runs)]
    else:
        sx0, sx1 = structure["side_range"]
        side = [r for r in runs if r["bbox"][0] >= sx0 - 2 and r["bbox"][2] <= sx1 + 2]
        left = [r for r in runs if r["bbox"][2] <= sx0 + 2 and r not in side]
        right = [r for r in runs if r["bbox"][0] >= sx1 - 2 and r not in side]
        # the main band must not enclose the side one: a stray note beyond it (`check` refuses real text there) is left out
        parts = [("side", side), ("main", left if len(left) >= len(right) else right)]
    bands = []
    for kind, members in parts:
        if not members:
            continue
        x0, x1 = round(min(r["bbox"][0] for r in members), 1), round(max(r["bbox"][2] for r in members), 1)
        if kind == "side":
            x0, x1 = round(min(x0, structure["side_range"][0]), 1), round(max(x1, structure["side_range"][1]), 1)
        bands.append({"x0": x0, "x1": x1, "kind": kind, "background": under(x0, x1), "lines": len(line_groups(members))})
    bands.sort(key=lambda b: b["x0"])
    return {"count": len(bands), "bands": bands}


def _structure_headings(structure: dict, shapes: list[dict], bands: list[dict]) -> list[dict]:
    """The headings of the structure (each with its `kind`): the band of a heading is the
    one of its column (worked out from its x), none for one across both."""
    found = []
    for h in structure["headings"]:
        main, bbox = h["row"]["main"], h["bbox"]
        wanted = "only" if structure["columns"] == "one" else h["column"]
        band = next((b for b in bands if b["kind"] == wanted), None)
        found.append({"page": h["row"]["page"], "text": h["text"], "bbox": bbox, "size": main["size"], "color": main["color"],
                      "weight": main["weight"], "family": main["family"], "italic": main["italic"],
                      "case": _case(h["text"]), "rule": _rule_under({"bbox": bbox, "page": h["row"]["page"]}, shapes, band),
                      "band": band["kind"] if band else None, "kind": h["kind"]})
    return found


def extract(pdf_path: Path, structure: dict | None = None) -> dict:
    """The style of the CV in *pdf_path* (see the module's docstring). `structure` is the CV's checked structure
    (`style_structure.check`, which makes it from the model's reading): the name, the headings and the columns come
    from it, and it decides the LinkedIn and layout verdicts. Without it (a print of a rebuilt template, which is
    compared by its text and icons) there are no name, headings or columns: `name` is None, `headings` and the bands
    empty. Raises FileNotFoundError for a missing file and pypdfium2's PdfiumError for one that is not a PDF."""
    doc = pdf_render.open_pdf(pdf_path)
    try:
        pages = _read_pages(doc)
        verdict = scan_verdict(pages)
        if structure and verdict["copyable"]:
            verdict = structure_verdict(structure)
        head = {"version": VERSION, "verdict": verdict, "page_count": len(doc)}
        if not verdict["copyable"] and verdict["reason"] != "layout":  # three columns keep every other key, for the draft
            return head
        style_icons.mark_icon_runs([r for p in pages for r in p["runs"]])
        runs = [r for p in pages for r in p["runs"]]
        shapes = [s for p in pages for s in p["shapes"]]
        page = {"size": pages[0]["size"], "background": pages[0]["background"], "margins": margins(pages),
                "bleed": _bleed(shapes, pages[0]["size"])}
        columns, name, headings = {"count": 0, "bands": []}, None, []
        if structure:
            columns = _structure_bands(structure, runs, shapes, pages[0]["size"][1])
            row = structure["name"]
            name = {"text": row["text"], "size": row["main"]["size"], "color": row["main"]["color"],
                    "family": row["main"]["family"]}
            headings = _structure_headings(structure, shapes, columns["bands"])
        return {**head, "page": page, "fonts": _fonts_used(runs), "colors": colors(runs, shapes), "name": name,
                "columns": columns, "headings": headings, "heading_style": heading_style(headings),
                "runs": [{k: v for k, v in r.items() if k not in _INTERNAL} for r in runs], "shapes": shapes,
                "icons": style_icons.find_icons(doc, pages), "photo": pages[0]["photo"]}
    finally:
        doc.close()
