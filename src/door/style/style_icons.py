"""The icons of a CV PDF as SVG paths (#148): glyphs of icon fonts, small vector drawings and small pictures, each
traced from a large render of its box (`style_trace`) and placed next to the text it belongs to. Part of
`style_extract`, which hands over what it read of the pages."""

from __future__ import annotations

import re
import unicodedata

from door.render import pdf_render
from door.style import style_trace

# every icon's `fill_rule`: the traced path has its holes as loops of their own
FILL_RULE = "evenodd"
# what a bullet of a list is set as: no icon, and no column of its own
BULLETS = set("•·‣◦▪●○■□–∙-*★☆")

# the fonts whose letters are pictures, matched on the name in lowercase letters and digits: icon fonts, the
# symbol fonts (a phone or an envelope set in Wingdings reads back as a stray "(") and TeX's symbol fonts
_ICON_FONT = re.compile(r"awesome|icon|symbol|material|glyph|fontello|ionicons|dingbats|wingdings|webdings|mtextra"
                        r"|marlett|^(cm(sy|mi|ex|bsy)|msam|msbm)")
_ICON_SIZE = 24.0  # points: a drawing larger than this is not an icon
_PICTURE_SIZE = 48.0  # points: nor is a picture, which is then a photo or a background
_SCALE = 10.0  # pixels per point an icon is traced at


def icon_font(name: str) -> bool:
    """Whether the font called `name` draws pictures for letters (an icon or a symbol font), for a PDF's runs and a
    DOCX's alike."""
    return bool(_ICON_FONT.search(re.sub(r"[^a-z0-9]", "", name.lower())))


def _pictographic(c: str) -> bool:
    """A symbol (category So) set aside for pictures: Miscellaneous Symbols and Dingbats (U+2600-27BF) and the emoji and
    pictograph planes from U+1F000. Technical marks, box drawing, block elements, geometric shapes (U+2300-25FF) and
    U+2B00-2BFF are text marks, and so are the rating stars, which are level marks like level dots."""
    return (unicodedata.category(c) == "So" and c not in BULLETS
            and ("\u2600" <= c <= "\u27bf" or c >= "\U0001f000"))


# what an emoji sequence has beside its pictographs: variation selectors, the joiner, skin-tone modifiers
_SEQUENCE = set("\u200d\ufe0e\ufe0f") | {chr(c) for c in range(0x1F3FB, 0x1F400)}


def glyph_only(text: str) -> bool:
    """At least one private-use, control or pictographic character, and nothing else but spaces, control characters and the
    pieces of an emoji sequence: what an icon font's glyphs read as. Letters, digits, punctuation, maths, arrows,
    currency, box drawing, geometric bullets and rating stars are ordinary text characters, whatever their font."""
    return (any(unicodedata.category(c) in ("Cc", "Co") and not c.isspace() or _pictographic(c) for c in text)
            and all(unicodedata.category(c) in ("Cc", "Co") or c.isspace() or c in _SEQUENCE or _pictographic(c)
                    for c in text))


def mark_icon_runs(runs: list[dict]) -> None:
    """Set `icon` on every run: true for the glyphs of an icon font (FontAwesome and the like): a font named like
    one, or a run of only private-use, control or pictographic characters. A run of bullets (and spaces) is no
    icon."""
    for run in runs:
        run["icon"] = not only_bullets(run["text"]) and bool(icon_font(run["font"]) or glyph_only(run["text"]))


def icon_fonts(runs: list[dict]) -> set[str]:
    """The fonts whose bullets are glyphs (`is_glyph`): every run of the font is an icon or bullets, one at least a
    real icon (marked by `mark_icon_runs`). A text font that draws one pictograph is none, so its bullets stay text; a
    symbol font of bullets only is none either, its dots being text."""
    by_font: dict[str, list[dict]] = {}
    for run in runs:
        by_font.setdefault(run["font"], []).append(run)
    return {name for name, its in by_font.items()
            if all(r["icon"] or only_bullets(r["text"]) for r in its) and any(r["icon"] for r in its)}


def only_bullets(text: str) -> bool:
    """Only bullet characters and spaces: a run of level dots or list bullets."""
    return all(c in BULLETS or c.isspace() for c in text)


def is_glyph(run: dict, fonts: set[str]) -> bool:
    """Whether `run` draws an icon, whose glyph reads back as a stray character: one marked `icon`, or a run of
    bullets only in one of `fonts` (`icon_fonts`; a level dot drawn with the icon font)."""
    return run["icon"] or (run["font"] in fonts and only_bullets(run["text"]))


def _luminance(color: str) -> float:
    r, g, b = style_trace.channels(color)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _background(run: dict, style: dict) -> str:
    """The fill behind *run*: its column band's, else its page's (`style["page"]`), else white."""
    x = (run["bbox"][0] + run["bbox"][2]) / 2
    band = next((b for b in style.get("columns", {}).get("bands", []) if b["x0"] <= x <= b["x1"] and b["background"]), None)
    return (band or {}).get("background") or style.get("page", {}).get("background") or "#ffffff"


def draft_edits(runs: list[dict], style: dict) -> list[tuple[int, list[float], str]]:
    """What a draft of the CV changes in a PDF's text, as (page, box, text) for `pdf_render.page_texts`: each icon
    left out (`icon`, text `""`) and each row of level dots in its colours said (`level_rows`)."""
    return [(r["page"], r["bbox"], "") for r in runs if r["icon"]] + level_rows(runs, style)


def level_rows(runs: list[dict], style: dict) -> list[tuple[int, list[float], str]]:
    """The rows of level dots whose level is in their colour, not their shape (#314), as (page, box, text) with the
    text `●●●●○`. On a line, bullet-only runs of two colours (`○ ○ ○ ○` dark, `○` pale) are one row: the filled
    colour is the one the CV uses for its accent or text (`style["colors"]`), else, when neither or both match, the
    one farther in lightness from the band it sits on. Once a CV has such a row, a row of one colour of the same
    glyph in its filled colour is all filled; any other row, and a row of three colours, is left as it is."""
    dots = [r for r in runs if r["text"].strip() and only_bullets(r["text"]) and r["color"]]
    rows: list[list[dict]] = []
    for r in sorted(dots, key=lambda r: (r["page"], r["bbox"][0])):
        mid = (r["bbox"][1] + r["bbox"][3]) / 2
        for row in rows:
            last = row[-1]
            if (last["page"] == r["page"] and abs((last["bbox"][1] + last["bbox"][3]) / 2 - mid) <= 0.3 * r["size"]
                    and r["bbox"][0] - last["bbox"][2] <= r["size"]):
                row.append(r)
                break
        else:
            rows.append([r])
    used = {c for c in (style.get("colors", {}).get("accent"), style.get("colors", {}).get("text")) if c}
    filled_by_glyph: dict[frozenset, str] = {}
    two = []
    for row in rows:
        colors = {r["color"] for r in row}
        if len(colors) == 2:
            mine = colors & used
            bg = _luminance(_background(row[0], style))
            filled = next(iter(mine)) if len(mine) == 1 else max(colors, key=lambda c: abs(_luminance(c) - bg))
            filled_by_glyph[_glyphs(row)] = filled
            two.append((row, filled))
    found = [(row[0]["page"], _box(row), "".join("●" if r["color"] == filled else "○" for r in row for c in r["text"] if not c.isspace()))
             for row, filled in two]
    for row in rows:
        if len({r["color"] for r in row}) == 1 and filled_by_glyph.get(_glyphs(row)) == row[0]["color"]:
            found.append((row[0]["page"], _box(row), "●" * sum(not c.isspace() for r in row for c in r["text"])))
    return found


def _glyphs(row: list[dict]) -> frozenset:
    return frozenset(c for r in row for c in r["text"] if not c.isspace())


def _box(row: list[dict]) -> list[float]:
    return [min(r["bbox"][0] for r in row), min(r["bbox"][1] for r in row),
            max(r["bbox"][2] for r in row), max(r["bbox"][3] for r in row)]


def _touching(a: list[float], b: list[float]) -> bool:
    return a[0] <= b[2] + 1 and b[0] <= a[2] + 1 and a[1] <= b[3] + 1 and b[1] <= a[3] + 1


def vector_icons(drawings: list[dict]) -> list[tuple[list[float], str]]:
    """Small drawings (four segments or more, the paths that are no rule, dot or box), those that touch put
    together: each as (box, colour)."""
    groups: list[dict] = []
    for shape in drawings:
        x0, y0, x1, y1 = shape["bbox"]
        if len(shape["segments"]) < 4 or x1 - x0 > _ICON_SIZE or y1 - y0 > _ICON_SIZE:
            continue
        merged = {"bbox": shape["bbox"], "color": shape["fill"] or shape["stroke"]}
        for g in [g for g in groups if _touching(g["bbox"], shape["bbox"])]:
            groups.remove(g)
            merged["bbox"] = [min(merged["bbox"][0], g["bbox"][0]), min(merged["bbox"][1], g["bbox"][1]),
                              max(merged["bbox"][2], g["bbox"][2]), max(merged["bbox"][3], g["bbox"][3])]
        groups.append(merged)
    return [(g["bbox"], g["color"]) for g in groups
            if g["bbox"][2] - g["bbox"][0] <= _ICON_SIZE and g["bbox"][3] - g["bbox"][1] <= _ICON_SIZE]


def _nearest(box: list[float], runs: list[dict]) -> tuple[dict, str] | None:
    """The run an icon belongs to and its side: the nearest run on its line, to its right first, else to its left."""
    mid = (box[1] + box[3]) / 2
    line = [r for r in runs if not r["icon"] and not r["rotated"] and r["bbox"][1] - 0.5 * r["size"] <= mid <= r["bbox"][3] + 0.5 * r["size"]]
    right = sorted((r for r in line if r["bbox"][0] >= box[2] - 1), key=lambda r: r["bbox"][0] - box[2])
    left = sorted((r for r in line if r["bbox"][2] <= box[0] + 1), key=lambda r: box[0] - r["bbox"][2])
    for side, found in (("right", right), ("left", left)):
        if found:
            return found[0], side
    return None


def kind_of(box: list[float], page: int, structure: dict | None) -> str | None:
    """The kind of icon (one of `templates.ICON_KINDS`) at `box` on `page`: the `kind` the model gave the contact line
    (`structure["contacts"]`) on the icon's own line, the nearest in x when several (a label and its value are rows of
    their own); None when no contact line is on it (or there is no structure)."""
    if not structure:
        return None
    mid = (box[1] + box[3]) / 2
    on_line = [c for c in structure["contacts"]
               if c["row"]["page"] == page and c["row"]["bbox"][1] - 0.5 <= mid <= c["row"]["bbox"][3] + 0.5]
    gap = lambda c: max(c["row"]["bbox"][0] - box[2], box[0] - c["row"]["bbox"][2], 0)  # noqa: E731
    return min(on_line, key=gap)["kind"] if on_line else None


def in_row(run: dict, row: dict) -> bool:
    """Whether `run` is a piece of the structure's `row` (the same page, its centre inside the row's box)."""
    x0, y0, x1, y1 = row["bbox"]
    cx, cy = (run["bbox"][0] + run["bbox"][2]) / 2, (run["bbox"][1] + run["bbox"][3]) / 2
    return run["page"] == row["page"] and x0 - 0.5 <= cx <= x1 + 0.5 and y0 - 0.5 <= cy <= y1 + 0.5


def _icon(page, number: int, box: list[float], color: str | None, source: str, font: str | None, runs: list[dict],
          structure: dict | None) -> dict | None:
    image, shown = pdf_render.render_box(page, box, _SCALE, pad=1.0)
    scale = image.width / (shown[2] - shown[0])
    traced = style_trace.trace(image, scale)
    if not traced:
        return None
    px = traced["bbox"]
    bbox = [round(shown[0] + px[0] / scale, 1), round(shown[1] + px[1] / scale, 1),
            round(shown[0] + px[2] / scale, 1), round(shown[1] + px[3] / scale, 1)]
    found = _nearest(bbox, runs)
    return {"page": number, "bbox": bbox, "source": source, "font": font, "color": color or traced["color"],
            "viewBox": traced["viewBox"], "d": traced["d"], "fill_rule": FILL_RULE,
            "near": {"text": found[0]["text"], "side": found[1]} if found else None,
            "kind": kind_of(bbox, number, structure)}


def find_icons(doc, pages: list[dict], structure: dict | None = None) -> list[dict]:
    """The icons of the document, in reading order: each page's icon-font runs, small drawings and small pictures
    that are not its photo (`photo_box` is the picture's own box, before what it shows of it was cut). Each has its
    `kind` from the structure's contact lines (`kind_of`)."""
    icons = []
    for number, (page, data) in enumerate(zip(doc, pages), 1):
        found = [(r["bbox"], r["color"], "font", r["font"]) for r in data["runs"] if r["icon"]]
        found += [(box, color, "vector", None) for box, color in vector_icons(data["drawings"])]
        for image in data["images"]:
            w, h = image["bbox"][2] - image["bbox"][0], image["bbox"][3] - image["bbox"][1]
            if image["bbox"] != data.get("photo_box") and 3 <= min(w, h) and max(w, h) <= _PICTURE_SIZE and 0.5 <= w / h <= 2:
                found.append((image["bbox"], None, "image", None))
        for box, color, source, font in found:
            icon = _icon(page, number, box, color, source, font, data["runs"], structure)
            if icon:
                icons.append(icon)
    return sorted(icons, key=lambda i: (i["page"], i["bbox"][1], i["bbox"][0]))
