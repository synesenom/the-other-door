"""Small PDFs for tests, and what a test reads back from a PDF, with pypdfium2 (no other PDF library).

`make_pdf(path, pages)` writes one A4 page per string, each line of it (split on newlines) set in
Helvetica from the top-left margin down; an empty string is a blank page.
"""

from __future__ import annotations

import ctypes
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as raw

_WIDTH, _HEIGHT, _MARGIN = 595, 842, 72


def make_pdf(path: Path, pages: list[str], size: float = 11.0) -> Path:
    """Write `pages` (one string per page) to `path` as a real, text-bearing PDF."""
    pdf = pdfium.PdfDocument.new()
    font = raw.FPDFText_LoadStandardFont(pdf, b"Helvetica")
    try:
        for text in pages:
            page = pdf.new_page(_WIDTH, _HEIGHT)
            y = _HEIGHT - _MARGIN
            for line in text.split("\n") if text else []:
                obj = raw.FPDFPageObj_CreateTextObj(pdf, font, ctypes.c_float(size))
                buf = ctypes.create_string_buffer((line + "\0").encode("utf-16-le"))
                raw.FPDFText_SetText(obj, ctypes.cast(buf, ctypes.POINTER(raw.FPDF_WCHAR)))
                raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, _MARGIN, y)
                raw.FPDFPage_InsertObject(page.raw, obj)
                y -= size * 1.3
            raw.FPDFPage_GenerateContent(page.raw)
            page.close()
        pdf.save(str(path))
    finally:
        raw.FPDFFont_Close(font)
        pdf.close()
    return Path(path)


def page_count(path: Path) -> int:
    pdf = pdfium.PdfDocument(str(path))
    try:
        return len(pdf)
    finally:
        pdf.close()


def page_text(path: Path, index: int = 0) -> str:
    """The text of one page, as `door.tailoring.pdf_render.page_texts` reads it."""
    from door.tailoring import pdf_render

    return pdf_render.page_texts(path)[index]


def font_names(path: Path, index: int = 0) -> set[str]:
    """The base font names of the text on one page, subset prefixes (`ABCDEF+`) dropped."""
    pdf = pdfium.PdfDocument(str(path))
    try:
        names = set()
        for obj in pdf[index].get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT]):
            font = raw.FPDFTextObj_GetFont(obj.raw)
            size = raw.FPDFFont_GetBaseFontName(font, None, 0)
            buf = ctypes.create_string_buffer(size)
            raw.FPDFFont_GetBaseFontName(font, buf, size)
            names.add(buf.value.decode("utf-8", "replace").split("+")[-1])
        return names
    finally:
        pdf.close()


def image_count(path: Path, index: int = 0) -> int:
    pdf = pdfium.PdfDocument(str(path))
    try:
        return sum(1 for _ in pdf[index].get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE]))
    finally:
        pdf.close()
