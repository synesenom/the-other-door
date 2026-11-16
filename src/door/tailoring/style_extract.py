"""Read a CV PDF's style as facts (#148, epic #144): fonts, sizes, colours, margins, columns, headings, drawn
shapes, icons as SVG paths, the photo. Pure and offline: pypdfium2 and Pillow, nothing written, no network.

`extract(pdf_path)` returns one dict (schema version 1, points, the origin at the top left, colours `#rrggbb`):
`verdict` first (`style_verdict` says when there is nothing to copy: a scan or a LinkedIn export; the other
keys are then left out), then `runs` (one per line piece of text), `fonts`, `page`, `colors`, `columns`,
`headings`, `shapes`, `icons`, `photo`. Fonts are only described (family, weight, italic, serif, fixed); looking
them up is another step. The icon tracer is `door.tailoring.style_trace`.
"""

from __future__ import annotations

import ctypes
import math
import re
from pathlib import Path

import pypdfium2.raw as raw

from door.tailoring import pdf_render

VERSION = 1

_WEIGHTS = [  # longest names first: "extrabold" holds "bold"
    ("extrablack", 950), ("ultrablack", 950), ("extralight", 200), ("ultralight", 200), ("extrabold", 800),
    ("ultrabold", 800), ("semibold", 600), ("demibold", 600), ("hairline", 100), ("regular", 400),
    ("medium", 500), ("normal", 400), ("light", 300), ("heavy", 800), ("black", 900), ("bold", 700),
    ("thin", 100), ("book", 400),
]
_STYLE_WORDS = {w for w, _ in _WEIGHTS} | {"italic", "oblique", "roman", "ital", "it"}
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


def _text_runs(page, number: int, height: float) -> tuple[list[dict], int]:
    """The visible text objects of a page as runs, and how many invisible ones (render mode 3) there were."""
    textpage = page.get_textpage()
    runs, invisible = [], 0
    try:
        for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT]):
            if raw.FPDFTextObj_GetTextRenderMode(obj.raw) == 3:
                invisible += 1
                continue
            obj.textpage = textpage
            text = obj.extract().strip()
            if not text:
                continue
            m = obj.get_matrix()
            size = round(obj.get_font_size() * math.hypot(m.c, m.d), 1)
            runs.append({"page": number, "text": text, "bbox": _bbox(obj, height), "size": size,
                         "color": _rgb(raw.FPDFPageObj_GetFillColor, obj), "rotated": abs(m.b) > abs(m.a),
                         "baseline": round(height - m.f, 1), "icon": False, **_font_facts(obj.get_font())})
    finally:
        textpage.close()
    return runs, invisible


def merge_runs(runs: list[dict]) -> list[dict]:
    """Chromium and Skia write one text object per glyph or word: join those on one line with the same font,
    size, colour and style whose gap is under a word space (a gap over a fifth of the size becomes a space)."""
    out: list[dict] = []
    for run in sorted(runs, key=lambda r: (r["page"], r["baseline"], r["bbox"][0])):
        last = out[-1] if out else None
        if last and _same_style(last, run) and abs(run["baseline"] - last["baseline"]) <= 0.3 * run["size"]:
            gap = run["bbox"][0] - last["bbox"][2]
            if -0.3 * run["size"] <= gap <= 0.6 * run["size"]:
                space = " " if gap > 0.2 * run["size"] and not run["text"].startswith(" ") else ""
                last.update(text=last["text"] + space + run["text"],
                            bbox=[last["bbox"][0], min(last["bbox"][1], run["bbox"][1]), run["bbox"][2],
                                  max(last["bbox"][3], run["bbox"][3])])
                continue
        out.append(dict(run))
    return out


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
    if fill and width <= _DOT_MAX and height <= _DOT_MAX and abs(width - height) <= 1 and (curves or len(points) >= 8):
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


# ---------- the whole read ----------

def _fonts_used(runs: list[dict]) -> list[dict]:
    fonts: dict[str, dict] = {}
    keys = ("font", "family", "weight", "italic", "serif", "fixed", "embedded")
    for run in runs:
        entry = fonts.setdefault(run["font"], {**{k: run[k] for k in keys}, "runs": 0, "chars": 0})
        entry["runs"] += 1
        entry["chars"] += sum(not c.isspace() for c in run["text"])
    return sorted(fonts.values(), key=lambda f: -f["chars"])


def extract(pdf_path: Path) -> dict:
    """The style of the CV in *pdf_path* (see the module's docstring). Raises FileNotFoundError for a missing
    file and pypdfium2's PdfiumError for one that is not a PDF."""
    doc = pdf_render._open(pdf_path)
    try:
        pages = []
        for number, page in enumerate(doc, 1):
            width, height = page.get_size()
            runs, _ = _text_runs(page, number, height)
            size = [round(width, 1), round(height, 1)]
            background, shapes = _page_background(_read_shapes(page, number, height), size)
            pages.append({"size": size, "runs": merge_runs(runs), "shapes": shapes, "background": background})
        head = {"version": VERSION, "verdict": style_verdict(pages), "producer": doc.get_metadata_value("Producer"),
                "creator": doc.get_metadata_value("Creator"), "page_count": len(doc)}
        if not head["verdict"]["copyable"]:
            return head
        runs = [r for p in pages for r in p["runs"]]
        shapes = [s for p in pages for s in p["shapes"] if s["kind"]]
        page = {"size": pages[0]["size"], "background": pages[0]["background"], "margins": margins(pages),
                "bleed": _bleed(shapes, pages[0]["size"])}
        return {**head, "page": page, "fonts": _fonts_used(runs),
                "runs": [{k: v for k, v in r.items() if k != "baseline"} for r in runs],
                "shapes": [{k: v for k, v in s.items() if k != "segments"} for s in shapes]}
    finally:
        doc.close()
