"""PDF reading and rendering helpers for The other door (pypdfium2, Apache-2.0/BSD).

- ``get_page_count(pdf_path)`` — return the number of pages in a PDF.
- ``page_texts(pdf_path)`` — the text of each page, one ``\\n`` per line break (``clean_text``).
- ``render_pdf_pages(pdf_path, output_dir)`` — render each page to a PNG image.

All raise ``FileNotFoundError`` when the PDF does not exist; a file that is not a readable PDF
raises pypdfium2's ``PdfiumError``.
PNG files are named ``<stem>_page_<N>.png`` (1-based), e.g. ``cv_page_1.png``.
Pages are rendered at 150 DPI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pypdfium2 as pdfium


_RENDER_DPI = 150
# pdfium marks a hyphen it took for a soft one (a word broken over two lines) with U+FFFE
_SOFT_HYPHEN = re.compile("\ufffe\n?")
# control characters other than tab and newline: what an icon glyph without text (a calendar, a pin) reads as
_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f]")


def clean_text(text: str) -> str:
    """*text* as pdfium read it, with ``\\n`` line breaks, the word a soft hyphen broke joined again and
    the control characters of icon glyphs dropped."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL.sub("", _SOFT_HYPHEN.sub("", text))


def open_pdf(pdf_path: Path) -> pdfium.PdfDocument:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    return pdfium.PdfDocument(str(pdf_path))


def get_page_count(pdf_path: Path) -> int:
    """Return the number of pages in *pdf_path*.

    Args:
        pdf_path: Path to an existing PDF file.

    Returns:
        Integer page count (>= 1).

    Raises:
        FileNotFoundError: If *pdf_path* does not exist.
    """
    doc = open_pdf(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


def page_texts(pdf_path: Path) -> list[str]:
    """The text of every page of *pdf_path*, in reading order, lines separated by ``\\n``.

    Raises:
        FileNotFoundError: If *pdf_path* does not exist.
    """
    doc = open_pdf(pdf_path)
    try:
        return [clean_text(page.get_textpage().get_text_range()) for page in doc]
    finally:
        doc.close()


def page_boxes(pdf_path: Path) -> list[tuple[float, float, list[tuple[float, float, float, float]]]]:
    """For every page of *pdf_path*: its ``(width, height)`` in points and the box ``(left, bottom, right, top)``
    of each printed character (whitespace and control characters left out), origin bottom-left.

    Raises:
        FileNotFoundError: If *pdf_path* does not exist.
    """
    doc = open_pdf(pdf_path)
    try:
        pages = []
        for page in doc:
            width, height = page.get_size()
            textpage = page.get_textpage()
            boxes = []
            for index, char in enumerate(textpage.get_text_range()):
                if char.isspace() or char < " " or char in "￾�":
                    continue
                boxes.append(tuple(textpage.get_charbox(index)))
            pages.append((width, height, boxes))
        return pages
    finally:
        doc.close()


def render_pdf_pages(pdf_path: Path, output_dir: Path) -> list[Path]:
    """Render every page of *pdf_path* to a PNG image in *output_dir*.

    Each page is saved as ``<stem>_page_<N>.png`` (1-based index) at
    150 DPI.

    Args:
        pdf_path: Path to an existing PDF file.
        output_dir: Directory where PNG files will be written (must exist).

    Returns:
        List of Paths to the created PNG files, one per page, in page order.

    Raises:
        FileNotFoundError: If *pdf_path* does not exist.
    """
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    doc = open_pdf(pdf_path)
    stem = pdf_path.stem
    results: list[Path] = []
    try:
        for i, page in enumerate(doc):
            image = page.render(scale=_RENDER_DPI / 72).to_pil()
            png_path = output_dir / f"{stem}_page_{i + 1}.png"
            image.save(png_path, format="PNG")
            results.append(png_path)
    finally:
        doc.close()
    return results


def render_box(page, bbox: list[float], scale: float, pad: float = 0.0):
    """The part of *page* in *bbox* (points, origin top left), padded by *pad* and kept inside the page, as a
    PIL image at *scale* pixels per point, with the box the image shows."""
    width, height = page.get_size()
    x0, y0, x1, y1 = max(bbox[0] - pad, 0.0), max(bbox[1] - pad, 0.0), min(bbox[2] + pad, width), min(bbox[3] + pad, height)
    image = page.render(scale=scale, crop=(x0, height - y1, width - x1, y0)).to_pil().convert("RGB")
    return image, [x0, y0, x1, y1]
