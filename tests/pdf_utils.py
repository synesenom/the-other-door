"""Small PDFs for tests, and what a test reads back from a PDF, with pypdfium2 (no other PDF library).

`make_pdf(path, pages)` writes one A4 page per string, each line of it (split on newlines) set in
Helvetica from the top-left margin down; an empty string is a blank page. `font=` sets it in a TrueType
file instead, embedded, for text Helvetica's standard encoding cannot hold (ő, ű, ○).
"""

from __future__ import annotations

import ctypes
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as raw

_WIDTH, _HEIGHT, _MARGIN = 595, 842, 72


def make_pdf(path: Path, pages: list[str], size: float = 11.0, font: Path | None = None) -> Path:
    """Write `pages` (one string per page) to `path` as a real, text-bearing PDF."""
    pdf = pdfium.PdfDocument.new()
    if font is None:
        handle = raw.FPDFText_LoadStandardFont(pdf, b"Helvetica")
    else:
        data = Path(font).read_bytes()
        font_data = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)   # kept alive until the save
        handle = raw.FPDFText_LoadFont(pdf, font_data, len(data), raw.FPDF_FONT_TRUETYPE, 1)
    try:
        for text in pages:
            page = pdf.new_page(_WIDTH, _HEIGHT)
            y = _HEIGHT - _MARGIN
            for line in text.split("\n") if text else []:
                obj = raw.FPDFPageObj_CreateTextObj(pdf, handle, ctypes.c_float(size))
                buf = ctypes.create_string_buffer((line + "\0").encode("utf-16-le"))
                raw.FPDFText_SetText(obj, ctypes.cast(buf, ctypes.POINTER(raw.FPDF_WCHAR)))
                raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, _MARGIN, y)
                raw.FPDFPage_InsertObject(page.raw, obj)
                y -= size * 1.3
            raw.FPDFPage_GenerateContent(page.raw)
            page.close()
        pdf.save(str(path))
    finally:
        raw.FPDFFont_Close(handle)
        pdf.close()
    return Path(path)


def page_count(path: Path) -> int:
    pdf = pdfium.PdfDocument(str(path))
    try:
        return len(pdf)
    finally:
        pdf.close()


def page_text(path: Path, index: int = 0) -> str:
    """The text of one page, as `door.render.pdf_render.page_texts` reads it."""
    from door.render import pdf_render

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


def path_count(path: Path, index: int = 0) -> int:
    """The drawn paths of one page (an SVG icon printed as a background is some)."""
    pdf = pdfium.PdfDocument(str(path))
    try:
        return sum(1 for _ in pdf[index].get_objects(filter=[raw.FPDF_PAGEOBJ_PATH]))
    finally:
        pdf.close()


def image_count(path: Path, index: int = 0) -> int:
    pdf = pdfium.PdfDocument(str(path))
    try:
        return sum(1 for _ in pdf[index].get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE]))
    finally:
        pdf.close()


_FONTS = {"F1": "Helvetica", "F2": "Helvetica-Bold", "F3": "Times-Roman", "F4": "Courier", "F5": "Helvetica-Oblique"}


def raw_pdf(pages: list[str] | str, size: tuple[float, float] = (595, 842),
            fonts: dict[str, str] | None = None, images: dict[str, tuple[int, int, bytes]] | None = None) -> bytes:
    """A PDF written by hand: one content stream per page, in PDF operators (origin bottom left).

    The fonts F1 Helvetica, F2 Helvetica-Bold, F3 Times-Roman, F4 Courier and F5 Helvetica-Oblique are there to
    use; `fonts` adds more as ``{resource name: BaseFont}`` (a Type1 font that is not embedded, only its name
    matters). `images` adds uncompressed RGB images as ``{resource name: (width, height, rgb bytes)}``, drawn with
    ``q w 0 0 h x y cm /Name Do Q``.
    """
    contents = [pages] if isinstance(pages, str) else list(pages)
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    catalog, tree = add(b""), add(b"")
    font_refs = {name: add(f"<</Type/Font/Subtype/Type1/BaseFont/{base}>>".encode())
                 for name, base in {**_FONTS, **(fonts or {})}.items()}
    image_refs = {name: add(f"<</Type/XObject/Subtype/Image/Width {w}/Height {h}/ColorSpace/DeviceRGB"
                            f"/BitsPerComponent 8/Length {len(data)}>>stream\n".encode() + data + b"\nendstream")
                  for name, (w, h, data) in (images or {}).items()}
    resources = ("<</Font<<" + "".join(f"/{n} {r} 0 R" for n, r in font_refs.items()) + ">>"
                 + ("/XObject<<" + "".join(f"/{n} {r} 0 R" for n, r in image_refs.items()) + ">>" if image_refs else "")
                 + ">>")
    kids = []
    for content in contents:
        data = content.encode("latin-1")
        stream = add(f"<</Length {len(data)}>>stream\n".encode() + data + b"\nendstream")
        kids.append(add(f"<</Type/Page/Parent {tree} 0 R/MediaBox[0 0 {size[0]} {size[1]}]/Contents {stream} 0 R"
                        f"/Resources{resources}>>".encode()))
    objs[catalog - 1] = f"<</Type/Catalog/Pages {tree} 0 R>>".encode()
    objs[tree - 1] = f"<</Type/Pages/Kids[{' '.join(f'{k} 0 R' for k in kids)}]/Count {len(kids)}>>".encode()
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer<</Size {len(objs) + 1}/Root {catalog} 0 R".encode() 
    out += f">>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
