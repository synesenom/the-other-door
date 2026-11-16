"""The two sides of scrub_pdf.py: the original's words (and its numbers of two digits or more), and the check
that none is left and nothing moved.

usage: scrub_check.py words <original.pdf> > words.json
       scrub_check.py check <original.pdf> <scrubbed.pdf> <words.json>
check prints how far icons (FontAwesome) and text runs moved, every original word or number still found in the
text, every word in the decompressed streams (PDF names, fonts and CMaps left out), links and metadata left,
and writes <scrubbed>-pdfium.png to look at.
Run with the project's environment (pypdfium2): `PYTHONPATH=src poetry run python -I scripts/style_corpus/scrub_check.py ...`
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
TOKEN = WORD + r"|\d{2,}"


def words(path: str) -> list[str]:
    pdf = pdfium.PdfDocument(path)
    text = "\n".join(p.get_textpage().get_text_range() for p in pdf)
    return sorted({w.lower() for w in re.findall(TOKEN, text)})


def numbers_left(banned: set[str], text: str) -> list[str]:
    """The original's numbers found inside a number of the scrubbed text."""
    found = re.findall(r"\d+", text)
    return sorted(b for b in banned if b.isdigit() and any(b in n for n in found))


def searchable(blob: bytes) -> bytes | None:
    """A PDF's bytes as the CV's words could be left in them: lower case, its /Names left out, an escaped letter
    (\\351, or a raw byte above 127) kept in its word; None for a font program or a CMap, whose words are their own."""
    if blob.startswith((b"%!", b"\x00\x01\x00\x00", b"true", b"OTTO", b"\x01\x00", b"/CIDInit")):
        return None
    return re.sub(rb"\\[0-7]{1,3}|[\x80-\xff]", b"x", re.sub(rb"/[^\s/<>\[\]()]+", b" ", blob)).lower()


def structure_left(blobs: list[bytes]) -> list[str]:
    """What a tagged PDF keeps of the CV's text outside its content: the structure tree, /ActualText and /Alt."""
    return sorted(m for m, pat in (("/StructTreeRoot", rb"/StructTreeRoot"), ("/ActualText", rb"/ActualText"),
                                   ("/Alt", rb"/Alt\b")) if any(re.search(pat, b) for b in blobs))


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
    if len(a) != len(b):  # glyph-wise text (Skia) joins words into runs: each must start where a glyph did
        far = max((min(max(abs(x - y) for x, y in zip(p, q)) for q in a) for p in b), default=0.0) if a else 0.0
        return f"count changed {len(a)} -> {len(b)}, each new run starts at most %.3f pt from an original one" % far
    return "%.3f pt" % max((max(abs(x - y) for x, y in zip(p, q)) for p, q in zip(a, b)), default=0.0)


def check(original: str, scrubbed: str, words_json: str) -> None:
    banned = set(json.loads(open(words_json).read()))
    a, b = pdfium.PdfDocument(original), pdfium.PdfDocument(scrubbed)
    print("icons moved at most:", shift(starts(a, True), starts(b, True)))
    print("text runs moved at most:", shift(starts(a, False), starts(b, False)))
    text = "\n".join(p.get_textpage().get_text_range() for p in b).lower()
    print("original words in the text:", sorted(set(re.findall(WORD, text)) & banned))
    print("original numbers in the text:", numbers_left(banned, text))
    data = open(scrubbed, "rb").read()
    blobs = [data]
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        try:
            blobs.append(zlib.decompress(m.group(1)))
        except zlib.error:
            continue
    blobs = [b for b in blobs if searchable(b) is not None]  # not a font program or a CMap
    print("structure left (tags, /ActualText, /Alt):", structure_left(blobs))
    blobs = [searchable(b) for b in blobs]
    print("original words (4+ letters) in the bytes:",
          sorted(w for w in banned if len(w) >= 4 and not w.isdigit()
                 and any(re.search(rb"\b" + re.escape(w.encode()) + rb"\b", x) for x in blobs)))
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
