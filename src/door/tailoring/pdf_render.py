"""PDF reading and rendering helpers for The other door (pypdfium2, Apache-2.0/BSD).

- ``get_page_count(pdf_path)`` — return the number of pages in a PDF.
- ``page_texts(pdf_path)`` — the text of each page, one ``\\n`` per line break.
- ``render_pdf_pages(pdf_path, output_dir)`` — render each page to a PNG image.

All raise ``FileNotFoundError`` when the PDF does not exist; a file that is not a readable PDF
raises pypdfium2's ``PdfiumError``.
PNG files are named ``<stem>_page_<N>.png`` (1-based), e.g. ``cv_page_1.png``.
Pages are rendered at 150 DPI.
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium


_RENDER_DPI = 150


def _open(pdf_path: Path) -> pdfium.PdfDocument:
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
    doc = _open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


def page_texts(pdf_path: Path) -> list[str]:
    """The text of every page of *pdf_path*, in reading order, lines separated by ``\\n``.

    Raises:
        FileNotFoundError: If *pdf_path* does not exist.
    """
    doc = _open(pdf_path)
    try:
        texts = []
        for page in doc:
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            texts.append(text.replace("\r\n", "\n").replace("\r", "\n"))
        return texts
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
    doc = _open(pdf_path)
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
