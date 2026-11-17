"""What a PDF's fonts measure (#199): the x-height and stem of each font as fractions of the font size,
and its text runs with their widths, read from the characters' boxes through pypdfium2. They are what
`door.style.fonts.plan` compares with each pinned family when no free copy of the font exists.

Only the ink boxes of what is printed are read: the embedded subset itself (`FPDFFont_GetFontData`) is never
touched, shipped or reused, and the descriptor's own ascent, weight and widths are not trusted (they are
approximations). Runs are in point units: ``(text, width, size)``.
"""

from __future__ import annotations

import ctypes
import math
import statistics
from pathlib import Path

import pypdfium2.raw as raw

from door.render import pdf_render

X_CHARS, STEM_CHARS = "xzvw", "l"
_MIN_RUN = 8   # characters, spaces included: a shorter run says little about a font's widths


def _font_name(textpage, index: int) -> str:
    buffer = ctypes.create_string_buffer(128)
    flags = ctypes.c_int()
    length = raw.FPDFText_GetFontInfo(textpage.raw, index, buffer, len(buffer), flags)
    return buffer.raw[:max(length - 1, 0)].decode("utf-8", "replace").split("+", 1)[-1] if length > 0 else ""


def _box(textpage, index: int) -> tuple[float, float, float, float]:
    left, right, bottom, top = (ctypes.c_double() for _ in range(4))
    raw.FPDFText_GetCharBox(textpage.raw, index, left, right, bottom, top)
    return left.value, right.value, bottom.value, top.value


def _effective_size(obj) -> float:
    """A text object's size as printed: its font size scaled by the matrix (Chromium and Pages draw at a size of 1
    or in CSS pixels and scale the page)."""
    size, matrix = ctypes.c_float(), raw.FS_MATRIX()
    raw.FPDFTextObj_GetFontSize(obj, size)
    raw.FPDFPageObj_GetMatrix(obj, matrix)
    return size.value * math.hypot(matrix.c, matrix.d)


def _chars(textpage) -> list[tuple[str, str, float, tuple[float, float, float, float]]]:
    """(character, font, size, (left, right, bottom, top)) for every printed character."""
    chars, sizes = [], {}
    for i in range(raw.FPDFText_CountChars(textpage.raw)):
        code = raw.FPDFText_GetUnicode(textpage.raw, i)
        if code in (0, 10, 13) or code >= 0xFFFE:
            chars.append(("\n", "", 0.0, (0.0, 0.0, 0.0, 0.0)))
            continue
        obj = raw.FPDFText_GetTextObject(textpage.raw, i)
        address = ctypes.cast(obj, ctypes.c_void_p).value
        if address not in sizes:
            sizes[address] = _effective_size(obj) if address else 0.0
        size = sizes[address]
        chars.append((chr(code), _font_name(textpage, i), size, _box(textpage, i)))
    return chars


def _split(chars) -> list[list]:
    """The characters as runs: the same font and size, one line, running forward."""
    runs, current = [], []
    for char in chars:
        ch, font, size, box = char
        if current:
            _, pfont, psize, pbox = current[-1]
            same = (ch != "\n" and font == pfont and abs(size - psize) < 0.05 and abs(box[2] - pbox[2]) < 0.4 * size
                    and box[0] >= pbox[0] - 0.5 * size)
            if not same:
                runs.append(current)
                current = []
        if ch != "\n":
            current.append(char)
    if current:
        runs.append(current)
    return runs


def measure(pdf_path: Path, fonts: list[dict]) -> dict[str, dict]:
    """For each font of `fonts` (the entries `style_extract.extract` returns) that has text in the PDF, by its base
    name: ``x_height`` and ``stem`` (fractions of the size, None when no letter to read them from)
    and ``runs`` (text, width, size)."""
    wanted = {f["font"] for f in fonts if not f.get("icon")}
    samples: dict[str, dict[str, list[float]]] = {n: {"x": [], "stem": []} for n in wanted}
    runs: dict[str, list[tuple[str, float, float]]] = {n: [] for n in wanted}
    doc = pdf_render.open_pdf(pdf_path)
    try:
        for page in doc:
            textpage = page.get_textpage()
            try:
                chars = _chars(textpage)
            finally:
                textpage.close()
            for ch, font, size, (left, right, bottom, top) in chars:
                if font not in wanted or size <= 0 or top <= bottom:
                    continue
                height, width = (top - bottom) / size, (right - left) / size
                if ch in X_CHARS:
                    samples[font]["x"].append(height)
                elif ch in STEM_CHARS:
                    samples[font]["stem"].append(width)
            for run in _split(chars):
                font, size = run[0][1], run[0][2]
                text = "".join(c[0] for c in run).rstrip()
                if font in wanted and len(text) >= _MIN_RUN:
                    last = run[len(text) - 1][3]
                    runs[font].append((text, round(last[1] - run[0][3][0], 2), size))
    finally:
        doc.close()

    def med(values: list[float]) -> float | None:
        return round(statistics.median(values), 3) if values else None
    return {n: {"x_height": med(s["x"]), "stem": med(s["stem"]), "runs": runs[n]}
            for n, s in samples.items() if runs[n] or any(s.values())}
