"""Read a CV PDF's style as facts (#148, epic #144): fonts, sizes, colours, margins, columns, headings, drawn
shapes, icons as SVG paths, the photo. Pure and offline: pypdfium2 and Pillow, nothing written, no network.

`extract(pdf_path)` returns one dict (schema version 1, points, the origin at the top left, colours `#rrggbb`):
`verdict` first (`style_verdict` says when there is nothing to copy: a scan or a LinkedIn export; the other
keys are then left out), then `runs` (one per piece of text on a line), `fonts`, `page` (size, margins, bleed,
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

from door import i18n
from door.tailoring import pdf_render, style_icons, style_trace

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

# headings
_SECTION_KINDS = tuple(i18n.CvSections.model_fields)

# nothing to copy
_LINKEDIN_HEADINGS = {"contact", "top skills", "languages", "certifications", "summary", "experience", "education"}
_PAGE_FOOTER = re.compile(r"page \d+ of \d+", re.I)
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

def _read_images(page, number: int, height: float) -> list[dict]:
    return [{"page": number, "bbox": _bbox(obj, height)} for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE])]


def _seen(page, bbox: list[float], background: str | None) -> tuple[list[float], str]:
    """What a picture shows of its box: the box of the pixels that differ from what is around it (a picture often
    has a blank margin), and its `shape`: `circle` when the corners of that box show the ground and the middle of
    each side does not, else `rect`."""
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
    mx, my = (ink[0] + ink[2]) // 2, (ink[1] + ink[3]) // 2
    corners = [(ink[0] + 1, ink[1] + 1), (ink[2] - 1, ink[1] + 1), (ink[0] + 1, ink[3] - 1), (ink[2] - 1, ink[3] - 1)]
    sides = [(mx, ink[1] + 1), (mx, ink[3] - 1), (ink[0] + 1, my), (ink[2] - 1, my)]
    round_ = (all(style_trace.distance(px[c], around) <= 12 for c in corners) and all(style_trace.distance(px[c], around) > 40 for c in sides)
              and style_trace.distance(px[mx, my], around) > 40)
    return box, "circle" if round_ else "rect"


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
    return low and (run["text"].strip().isdigit() or bool(_PAGE_FOOTER.fullmatch(run["text"].strip())))


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


def column_bands(pages: list[dict], shapes: list[dict]) -> dict:
    """The column bands of the text: stacks of lines apart by a gap. A band needs four lines that stand together
    (the dates down the right of a single column, or a note in the margin, are no column) and a twelfth of the
    lines. One band is `only`; with more, the narrowest, if under 40% of the text's width or on a coloured box, is
    the `side`, the others `main`. `background` is the fill of a box covering most of the page's height."""
    runs = [r for p in pages for r in p["runs"] if not r["rotated"] and not r["icon"]
            and not (len(r["text"]) <= 1 or all(c in style_icons.BULLETS for c in r["text"]))]
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
    boxes = [s for s in shapes if s["kind"] == "box" and s["fill"] and s["bbox"][3] - s["bbox"][1] >= 0.8 * height]

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
        if len({(r["family"], r["weight"], r["color"], r["italic"]) for r in line}) != 1:
            continue
        first = line[0]
        units.append({"page": first["page"], "text": _joined(line), "size": max(r["size"] for r in line),
                      "mixed": len({r["size"] for r in line}) > 1, "color": first["color"], "weight": first["weight"],
                      "family": first["family"], "italic": first["italic"],
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
        return (u["family"], u["size"], u["color"], u["weight"], u["mixed"], u["italic"])

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
                          "weight": u["weight"], "family": u["family"], "italic": u["italic"], "case": _case(u["text"]),
                          "rule": _rule_under(u, shapes, band)})
    return found


def heading_style(headings: list[dict]) -> dict | None:
    """What most headings share: size, colour, weight, family, case, italic and (if most have one) their rule."""
    if not headings:
        return None
    keys = ("size", "color", "weight", "family", "case", "italic")
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
    suffix; None for a PDF, which `extract` judges by what is in it. Called where the file is taken in."""
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return None
    return {"copyable": False, "reason": "not_pdf", "detail": f"a {suffix[1:] or 'file'} has no layout to copy"}


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


# ---------- the whole read ----------

def _fonts_used(runs: list[dict]) -> list[dict]:
    fonts: dict[str, dict] = {}
    keys = ("font", "family", "weight", "italic", "serif", "fixed", "embedded", "type3")
    for run in runs:
        entry = fonts.setdefault(run["font"], {**{k: run[k] for k in keys}, "icon": True, "runs": 0, "chars": 0})
        # a bullet drawn from an icon font (the rating's empty dot) is no reason to fetch that font
        entry["icon"] = entry["icon"] and (run["icon"] or all(c in style_icons.BULLETS or c.isspace() for c in run["text"]))
        entry["runs"] += 1
        entry["chars"] += sum(not c.isspace() for c in run["text"])
    return sorted(fonts.values(), key=lambda f: -f["chars"])


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


def extract(pdf_path: Path) -> dict:
    """The style of the CV in *pdf_path* (see the module's docstring). Raises FileNotFoundError for a missing
    file and pypdfium2's PdfiumError for one that is not a PDF."""
    doc = pdf_render.open_pdf(pdf_path)
    try:
        pages = _read_pages(doc)
        head = {"version": VERSION, "verdict": style_verdict(pages), "page_count": len(doc)}
        if not head["verdict"]["copyable"]:
            return head
        style_icons.mark_icon_runs([r for p in pages for r in p["runs"]])
        runs = [r for p in pages for r in p["runs"]]
        shapes = [s for p in pages for s in p["shapes"]]
        page = {"size": pages[0]["size"], "background": pages[0]["background"], "margins": margins(pages),
                "bleed": _bleed(shapes, pages[0]["size"])}
        columns = column_bands(pages, shapes)
        name = find_name(runs)
        headings = find_headings(runs, shapes, columns["bands"], name)
        return {**head, "page": page, "fonts": _fonts_used(runs), "colors": colors(runs, shapes), "name": name,
                "columns": columns, "headings": headings, "heading_style": heading_style(headings),
                "runs": [{k: v for k, v in r.items() if k not in _INTERNAL} for r in runs], "shapes": shapes,
                "icons": style_icons.find_icons(doc, pages), "photo": pages[0]["photo"]}
    finally:
        doc.close()
