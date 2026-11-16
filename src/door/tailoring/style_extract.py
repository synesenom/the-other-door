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
        runs: list[dict] = []
        size = None
        for number, page in enumerate(doc, 1):
            width, height = page.get_size()
            size = size or [round(width, 1), round(height, 1)]
            page_runs, _ = _text_runs(page, number, height)
            runs += merge_runs(page_runs)
        return {"version": VERSION, "producer": doc.get_metadata_value("Producer"),
                "creator": doc.get_metadata_value("Creator"), "page_count": len(doc),
                "page": {"size": size}, "fonts": _fonts_used(runs),
                "runs": [{k: v for k, v in r.items() if k != "baseline"} for r in runs]}
    finally:
        doc.close()
