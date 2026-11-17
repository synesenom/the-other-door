"""The icons of a CV PDF as SVG paths (#148): glyphs of icon fonts, small vector drawings and small pictures, each
traced from a large render of its box (`style_trace`) and placed next to the text it belongs to. Part of
`style_extract`, which hands over what it read of the pages."""

from __future__ import annotations

import re

from door.tailoring import pdf_render, style_trace

# every icon's `fill_rule`: the traced path has its holes as loops of their own
FILL_RULE = "evenodd"
# what a bullet of a list is set as: no icon, and no column of its own
BULLETS = set("•·‣◦▪●○■□–∙-*")

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


def glyph_only(text: str) -> bool:
    """Only control characters, private use or dingbats: what an icon font's glyphs read as."""
    return all(c < " " or "" <= c <= "" or "✀" <= c <= "➿" for c in text)


def mark_icon_runs(runs: list[dict]) -> None:
    """Set `icon` on every run: true for the glyphs of an icon font (FontAwesome and the like): a font named like
    one, a run of only private-use, control or dingbat characters, or a font whose runs are all a character or two
    of symbols. A bullet is no icon."""
    short: dict[str, bool] = {}
    for run in runs:
        short[run["font"]] = short.get(run["font"], True) and len(run["text"]) <= 2 and not run["text"].isalnum()
    for run in runs:
        run["icon"] = not all(c in BULLETS for c in run["text"]) and bool(
            icon_font(run["font"]) or glyph_only(run["text"]) or short[run["font"]])


def icon_fonts(runs: list[dict]) -> set[str]:
    """The fonts of the runs `mark_icon_runs` marked icons."""
    return {r["font"] for r in runs if r["icon"]}


def only_bullets(text: str) -> bool:
    """Only bullet characters and spaces: a run of level dots or list bullets."""
    return all(c in BULLETS or c.isspace() for c in text)


def is_glyph(run: dict, fonts: set[str]) -> bool:
    """Whether `run` draws an icon, whose glyph reads back as a stray character: one marked `icon`, or a run of
    bullets only in one of `fonts` (`icon_fonts`; a level dot drawn with the icon font)."""
    return run["icon"] or (run["font"] in fonts and only_bullets(run["text"]))


def stray_glyph(run: dict) -> bool:
    """Whether `run` reads back in a PDF's text as stray characters a draft of the CV leaves out: an icon's glyph
    (`icon`), not level dots or bullets, which say something (`●●●○○` is 3 of 5; a list), even drawn with the icon
    font (#313)."""
    return run["icon"] and not only_bullets(run["text"])


def _luminance(color: str) -> float:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.299 * r + 0.587 * g + 0.114 * b


def level_rows(runs: list[dict]) -> list[tuple[int, list[float], str]]:
    """The rows of level dots whose level is in their colour, not their shape (#314): on a line, bullet-only runs
    of two colours (`○ ○ ○ ○` dark, `○` pale), as (page, box, text) with the text `●●●●○`: the darker colour is
    filled. Dots of one colour say nothing by it and are left out."""
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
    found = []
    for row in rows:
        colors = {r["color"] for r in row}
        if len(colors) != 2:
            continue
        filled = min(colors, key=_luminance)
        text = "".join("●" if r["color"] == filled else "○" for r in row for c in r["text"] if not c.isspace())
        box = [min(r["bbox"][0] for r in row), min(r["bbox"][1] for r in row),
               max(r["bbox"][2] for r in row), max(r["bbox"][3] for r in row)]
        found.append((row[0]["page"], box, text))
    return found


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


def near(box: list[float], runs: list[dict]) -> dict | None:
    """The text an icon belongs to: the nearest run on its line, to its right first, else to its left."""
    mid = (box[1] + box[3]) / 2
    line = [r for r in runs if not r["icon"] and not r["rotated"] and r["bbox"][1] - 0.5 * r["size"] <= mid <= r["bbox"][3] + 0.5 * r["size"]]
    right = sorted((r for r in line if r["bbox"][0] >= box[2] - 1), key=lambda r: r["bbox"][0] - box[2])
    left = sorted((r for r in line if r["bbox"][2] <= box[0] + 1), key=lambda r: box[0] - r["bbox"][2])
    for side, found in (("right", right), ("left", left)):
        if found:
            return {"text": found[0]["text"], "side": side}
    return None


def _icon(page, number: int, box: list[float], color: str | None, source: str, font: str | None, runs: list[dict]) -> dict | None:
    image, shown = pdf_render.render_box(page, box, _SCALE, pad=1.0)
    scale = image.width / (shown[2] - shown[0])
    traced = style_trace.trace(image, scale)
    if not traced:
        return None
    px = traced["bbox"]
    bbox = [round(shown[0] + px[0] / scale, 1), round(shown[1] + px[1] / scale, 1),
            round(shown[0] + px[2] / scale, 1), round(shown[1] + px[3] / scale, 1)]
    return {"page": number, "bbox": bbox, "source": source, "font": font, "color": color or traced["color"],
            "viewBox": traced["viewBox"], "d": traced["d"], "fill_rule": FILL_RULE, "near": near(bbox, runs)}


def find_icons(doc, pages: list[dict]) -> list[dict]:
    """The icons of the document, in reading order: each page's icon-font runs, small drawings and small pictures
    that are not its photo (`photo_box` is the picture's own box, before what it shows of it was cut)."""
    icons = []
    for number, (page, data) in enumerate(zip(doc, pages), 1):
        found = [(r["bbox"], r["color"], "font", r["font"]) for r in data["runs"] if r["icon"]]
        found += [(box, color, "vector", None) for box, color in vector_icons(data["drawings"])]
        for image in data["images"]:
            w, h = image["bbox"][2] - image["bbox"][0], image["bbox"][3] - image["bbox"][1]
            if image["bbox"] != data.get("photo_box") and 3 <= min(w, h) and max(w, h) <= _PICTURE_SIZE and 0.5 <= w / h <= 2:
                found.append((image["bbox"], None, "image", None))
        for box, color, source, font in found:
            icon = _icon(page, number, box, color, source, font, data["runs"])
            if icon:
                icons.append(icon)
    return sorted(icons, key=lambda i: (i["page"], i["bbox"][1], i["bbox"][0]))
