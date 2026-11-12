"""A stand-in `tectonic` for the journeys: `python tectonic.py <world dir> --outdir DIR FILE.tex`.

It lays the document's text out on A4 pages with pypdfium2 (Helvetica, wrapped by its widths), so a
PDF's page count follows the length of what the tailor or `revise` wrote, and door renders real page
images from it. A `.tex` containing `\\worldfail` fails as a LaTeX error does. Only the text matters
here: headings (`\\section{..}`) are set larger, other commands are dropped.
"""

import ctypes
import re
import sys
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as raw

# Helvetica's advance widths (per 1000 of the font size) for ASCII 32-126; a few others below.
_ASCII = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556,
          556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667,
          556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556,
          556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722,
          500, 500, 500, 334, 260, 334, 584]
_OTHER = {"æ": 889, "ø": 611, "å": 556, "Æ": 1000, "Ø": 778, "Å": 667}  # anything else counts as 556
WIDTH, HEIGHT = 595, 842
LEFT, RIGHT, TOP, BOTTOM = 64, 531, 64, 790  # the text box, in points from the page's top-left


def text_width(text, size):
    return sum(_ASCII[ord(c) - 32] if 32 <= ord(c) < 127 else _OTHER.get(c, 556) for c in text) * size / 1000


def wrap(text, size):
    """The lines `text` takes in the box, each line of
    `text` on its own, whole words where they fit, a word wider than the box broken char by char."""
    out = []
    room, space = RIGHT - LEFT, text_width(" ", size)
    for source in text.split("\n"):
        line, rest = "", room
        for word in source.split(" "):
            w = text_width(word, size)
            if rest >= w:
                line, rest = line + word + " ", rest - w - space
                continue
            if line:
                out.append(line.rstrip())
            line, rest = "", room
            if w <= room:
                line, rest = word + " ", room - w - space
                continue
            for c in word:
                if text_width(line, size) <= room - text_width(c, size):
                    line += c
                else:
                    out.append(line)
                    line = c
            line += " "
            rest = room - text_width(line, size)
        out.append(line.rstrip())
    return out


def needed(text, size):
    """The height `text` takes: a 1.374 line height plus the last line's descent."""
    return len(wrap(text, size)) * 1.374 * size + 0.299 * size


def place(page, text, size, y):
    """Set `text` in the box from `y` (points from the top) down."""
    for i, line in enumerate(wrap(text, size)):
        if not line:
            continue
        obj = raw.FPDFPageObj_CreateTextObj(pdf, font, ctypes.c_float(size))
        buf = ctypes.create_string_buffer((line + "\0").encode("utf-16-le"))
        raw.FPDFText_SetText(obj, ctypes.cast(buf, ctypes.POINTER(raw.FPDF_WCHAR)))
        raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, LEFT, HEIGHT - (y + 1.075 * size + i * 1.374 * size))
        raw.FPDFPage_InsertObject(page.raw, obj)


args = sys.argv[2:]
if args[:1] == ["--version"]:
    print("Tectonic 0.15.0")
    sys.exit(0)
outdir = Path(args[args.index("--outdir") + 1])
tex_path = Path(args[-1])
tex = tex_path.read_text(encoding="utf-8")
if "\\worldfail" in tex:
    sys.stderr.write(f"error: {tex_path.name}:12: Undefined control sequence \\worldfail\n")
    sys.exit(1)

body = tex.split("\\begin{document}", 1)[-1].split("\\end{document}", 1)[0]
blocks = []
for para in re.split(r"\n\s*\n", body):
    heading = re.match(r"\s*\\(?:section|subsection)\*?\{(.*?)\}", para)
    text = re.sub(r"%.*", "", para)
    text = re.sub(r"\\(?:section|subsection)\*?\{(.*?)\}", "", text)
    text = re.sub(r"\\textbf\{(.*?)\}|\\emph\{(.*?)\}", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"\\item\s*", "• ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", "", text)
    text = text.replace("\\&", "&").replace("\\%", "%").replace("~", " ").replace("--", "–")
    text = re.sub(r"[{}\\]", "", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    if heading:
        blocks.append(("h", heading.group(1)))
    if text:
        blocks.append(("p", text))

pdf = pdfium.PdfDocument.new()
font = raw.FPDFText_LoadStandardFont(pdf, b"Helvetica")
pages = [pdf.new_page(WIDTH, HEIGHT)]
y = float(TOP)
for kind, text in blocks:
    size = 14 if kind == "h" else 10
    while True:
        if y + needed(text, size) <= BOTTOM:
            place(pages[-1], text, size, y)
            y += needed(text, size) + (10 if kind == "h" else 8)
            break
        if y == TOP:  # longer than a whole page: set what fits, the rest goes on the next one
            words = text.split()
            first, text = " ".join(words[: len(words) // 2]), " ".join(words[len(words) // 2:])
            if TOP + needed(first, size) <= BOTTOM:
                place(pages[-1], first, size, y)
        # did not fit: the next page, and the text again from there
        pages.append(pdf.new_page(WIDTH, HEIGHT))
        y = float(TOP)
for page in pages:
    raw.FPDFPage_GenerateContent(page.raw)
pdf.save(str(outdir / tex_path.with_suffix(".pdf").name))
