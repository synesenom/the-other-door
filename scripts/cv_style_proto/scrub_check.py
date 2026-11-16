"""The two sides of scrub_pdf.py: the original's words, and the check that none is left and nothing moved.

usage: scrub_check.py words <original.pdf> > words.json
       scrub_check.py check <original.pdf> <scrubbed.pdf> <words.json>
check prints how far icons (FontAwesome) and text runs moved, every original word still found in the text
or in the decompressed streams, links and metadata left, and writes <scrubbed>-pdfium.png to look at.
Run with the project's environment (pypdfium2): `PYTHONPATH=src poetry run python -I scripts/cv_style_proto/scrub_check.py ...`
"""
from __future__ import annotations

import ctypes
import json
import re
import sys
import zlib

import pypdfium2 as pdfium
import pypdfium2.raw as raw

WORD = r"[^\W\d_]{3,}"


def words(path: str) -> list[str]:
    pdf = pdfium.PdfDocument(path)
    text = "\n".join(p.get_textpage().get_text_range() for p in pdf)
    return sorted({w.lower() for w in re.findall(WORD, text)})


def starts(pdf: pdfium.PdfDocument, icon: bool) -> list[tuple[float, float]]:
    found = []
    for page in pdf:
        for o in page.get_objects(max_depth=0):
            if o.type != raw.FPDF_PAGEOBJ_TEXT:
                continue
            name = ctypes.create_string_buffer(256)
            raw.FPDFFont_GetBaseFontName(raw.FPDFTextObj_GetFont(o.raw), name, 256)
            if (b"FontAwesome" in name.value) != icon:
                continue
            box = [ctypes.c_float() for _ in range(4)]
            raw.FPDFPageObj_GetBounds(o.raw, *(ctypes.byref(x) for x in box))
            found.append((box[0].value, box[1].value))
    return found


def shift(a: list, b: list) -> str:
    if len(a) != len(b):
        return f"count changed {len(a)} -> {len(b)}"
    return "%.3f pt" % max((max(abs(x - y) for x, y in zip(p, q)) for p, q in zip(a, b)), default=0.0)


def check(original: str, scrubbed: str, words_json: str) -> None:
    banned = set(json.loads(open(words_json).read()))
    a, b = pdfium.PdfDocument(original), pdfium.PdfDocument(scrubbed)
    print("icons moved at most:", shift(starts(a, True), starts(b, True)))
    print("text runs moved at most:", shift(starts(a, False), starts(b, False)))
    text = "\n".join(p.get_textpage().get_text_range() for p in b).lower()
    print("original words in the text:", sorted(set(re.findall(WORD, text)) & banned))
    data = open(scrubbed, "rb").read()
    blobs = [data]
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        try:
            blob = zlib.decompress(m.group(1))
        except zlib.error:
            continue
        if not blob.startswith(b"%!"):  # font programs and CMaps: their own words, not the CV's
            blobs.append(blob)
    print("original words (4+ letters) in the bytes:",
          sorted(w for w in banned if len(w) >= 4
                 and any(re.search(rb"\b" + re.escape(w.encode()) + rb"\b", x.lower()) for x in blobs)))
    print("links:", sum(raw.FPDFPage_GetAnnotCount(p.raw) for p in b),
          "| metadata:", {k: v for k, v in b.get_metadata_dict().items() if v})
    b[0].render(scale=150 / 72).to_pil().save(scrubbed.removesuffix(".pdf") + "-pdfium.png")


if __name__ == "__main__":
    if sys.argv[1:2] == ["words"]:
        print(json.dumps(words(sys.argv[2]), ensure_ascii=False))
    elif sys.argv[1:2] == ["check"]:
        check(*sys.argv[2:5])
    else:
        raise SystemExit(__doc__)
