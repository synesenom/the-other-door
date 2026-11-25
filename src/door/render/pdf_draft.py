"""The text of an uploaded CV PDF as a draft reads it (#266, #313): pdfium's text with each icon-font glyph left out
(it reads back as a stray "!" or "½") and each row of level dots said in its colours (`●●●○○`), a level that the dots'
colour shows and their shape does not. Bullets and dots are text, whatever font draws them."""

from __future__ import annotations

import ctypes
import re
import unicodedata
from pathlib import Path

import pypdfium2.raw as raw

from door.render import pdf_render

# the fonts whose letters are pictures, matched on the name in lowercase letters and digits: icon fonts and symbol
# fonts (a phone or an envelope set in Wingdings reads back as a stray "(")
_ICON_FONT = re.compile(r"awesome|icon|symbol|material|glyph|fontello|ionicons|dingbats|wingdings|webdings|mtextra"
                        r"|marlett|^(cm(sy|mi|ex|bsy)|msam|msbm)")
BULLETS = set("•·‣◦▪●○■□–∙-*★☆")
_SEQUENCE = set("‍︎️") | {chr(c) for c in range(0x1F3FB, 0x1F400)}  # an emoji sequence's other pieces


def icon_font(name: str) -> bool:
    """Whether the font called `name` draws pictures for letters (an icon or a symbol font)."""
    return bool(_ICON_FONT.search(re.sub(r"[^a-z0-9]", "", name.lower())))


def _pictographic(c: str) -> bool:
    """A symbol (category So) set aside for pictures: Miscellaneous Symbols and Dingbats (U+2600-27BF) and the emoji and
    pictograph planes from U+1F000. Box drawing, geometric shapes and rating stars are text marks."""
    return unicodedata.category(c) == "So" and c not in BULLETS and ("☀" <= c <= "➿" or c >= "\U0001f000")


def glyph_only(text: str) -> bool:
    """At least one private-use, control or pictographic character, and nothing else but spaces, control characters and
    the pieces of an emoji sequence: what an icon font's glyphs read as."""
    return (any(unicodedata.category(c) in ("Cc", "Co") and not c.isspace() or _pictographic(c) for c in text)
            and all(unicodedata.category(c) in ("Cc", "Co") or c.isspace() or c in _SEQUENCE or _pictographic(c)
                    for c in text))


def _only_bullets(text: str) -> bool:
    return all(c in BULLETS or c.isspace() for c in text)


def _luminance(color: tuple[int, int, int]) -> float:
    r, g, b = color
    return 0.299 * r + 0.587 * g + 0.114 * b


def _runs(page, height: float) -> list[dict]:
    """The visible text objects of a page: text, font name, fill colour and box (points from the top left)."""
    textpage = page.get_textpage()
    runs = []
    try:
        for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT]):
            if raw.FPDFTextObj_GetTextRenderMode(obj.raw) == 3:  # invisible: an OCR layer
                continue
            obj.textpage = textpage
            text = obj.extract().strip()
            if not text:
                continue
            r, g, b, a = (ctypes.c_uint() for _ in range(4))
            raw.FPDFPageObj_GetFillColor(obj.raw, r, g, b, a)
            left, bottom, right, top = obj.get_bounds()
            runs.append({"text": text, "font": obj.get_font().get_base_name().split("+", 1)[-1],
                         "color": (r.value, g.value, b.value), "bbox": [left, height - top, right, height - bottom],
                         "size": max(top - bottom, 1.0)})
    finally:
        textpage.close()
    return runs


def _level_rows(runs: list[dict]) -> list[tuple[list[float], str]]:
    """The rows of level dots whose level is in their colour, as (box, text) with the text `●●●●○`. On a line,
    bullet-only runs of two colours are one row: the filled colour is the one farther in lightness from the white
    page. Once a CV has such a row, a row of one colour of the same glyph in its filled colour is all filled; any
    other row, and a row of three colours, is left as it is."""
    dots = sorted((r for r in runs if _only_bullets(r["text"])), key=lambda r: r["bbox"][0])
    rows: list[list[dict]] = []
    for r in dots:
        mid = (r["bbox"][1] + r["bbox"][3]) / 2
        for row in rows:
            last = row[-1]
            if (abs((last["bbox"][1] + last["bbox"][3]) / 2 - mid) <= 0.3 * r["size"]
                    and r["bbox"][0] - last["bbox"][2] <= r["size"]):
                row.append(r)
                break
        else:
            rows.append([r])

    def glyphs(row):
        return frozenset(c for r in row for c in r["text"] if not c.isspace())

    def box(row):
        return [min(r["bbox"][i] for r in row) for i in (0, 1)] + [max(r["bbox"][i] for r in row) for i in (2, 3)]

    def count(row):
        return sum(not c.isspace() for r in row for c in r["text"])

    filled_by_glyph, found = {}, []
    for row in rows:
        colors = {r["color"] for r in row}
        if len(colors) == 2:
            filled = max(colors, key=lambda c: 255 - _luminance(c))
            filled_by_glyph[glyphs(row)] = filled
            found.append((box(row), "".join("●" if r["color"] == filled else "○"
                                            for r in row for c in r["text"] if not c.isspace())))
    for row in rows:
        if len({r["color"] for r in row}) == 1 and filled_by_glyph.get(glyphs(row)) == row[0]["color"]:
            found.append((box(row), "●" * count(row)))
    return found


def _edits(runs: list[dict]) -> list[tuple[list[float], str]]:
    """What a draft changes on a page, as (box, text): each icon left out (text `""`), each level row said."""
    icons = [(r["bbox"], "") for r in runs if not _only_bullets(r["text"]) and (icon_font(r["font"]) or glyph_only(r["text"]))]
    return icons + _level_rows(runs)


def _edited(textpage, text: str, height: float, edits: list[tuple[list[float], str]]) -> str:
    """`text` of a page with the characters whose centre is in a box of `edits` replaced by its text where the first
    of them stood."""
    out, put = [], set()
    for i, c in enumerate(text):
        left, bottom, right, top = textpage.get_charbox(i)
        x, y = (left + right) / 2, height - (bottom + top) / 2
        hit = next((n for n, ((x0, y0, x1, y1), _) in enumerate(edits)
                    if right > left and x0 - 0.5 <= x <= x1 + 0.5 and y0 - 0.5 <= y <= y1 + 0.5), None)
        if hit is None:
            out.append(c)
        elif hit not in put:
            out.append(edits[hit][1])
            put.add(hit)
    return "".join(out)


MAX_PAGES = 30  # a real CV is a few pages
MAX_TEXT = 300_000


def draft_text(pdf_path: Path) -> str:
    """The text of every page of the PDF as a draft reads it (see the module).

    Raises:
        FileNotFoundError: If `pdf_path` does not exist.
        ValueError: If it has more than `MAX_PAGES` pages or more than `MAX_TEXT` characters of text: not a CV.
    """
    doc = pdf_render.open_pdf(pdf_path)
    try:
        if len(doc) > MAX_PAGES:
            raise ValueError(f"{pdf_path.name} has {len(doc)} pages, more than the {MAX_PAGES} of a CV")
        texts, size = [], 0
        for page in doc:
            height = page.get_height()
            edits = _edits(_runs(page, height))
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            texts.append(pdf_render.clean_text(_edited(textpage, text, height, edits) if edits else text))
            size += len(texts[-1])
            if size > MAX_TEXT:
                raise ValueError(f"{pdf_path.name} has more than {MAX_TEXT} characters of text, too much for a CV")
        return "\n".join(texts).strip()
    finally:
        doc.close()
