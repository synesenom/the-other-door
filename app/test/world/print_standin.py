"""A stand-in for the Chromium print in the journeys (#146): `html_pdf.print_html` replaced, and a
`chrome-headless-shell` on PATH that answers `--version`, so `doctor` finds a printer that starts.

It lays the page's text out on A4 pages with pypdfium2 (Helvetica, wrapped by its widths), so a PDF's page
count follows the length of what the tailor or `revise` wrote, and door renders real page images from it.
Only the text matters here: `<h1>`..`<h3>` are set larger, `<li>` gets a bullet, the rest is paragraphs. A body
holding the word `worldfail` fails as a print does (`PrintError`). Installed by `edges.py` (the server, the CLI)
and by the stand-in tailor's own `compile` (claude.py) through `install()`.
"""

import ctypes
import shutil
import sys
from html.parser import HTMLParser
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


def place(pdf, font, page, text, size, y):
    """Set `text` in the box from `y` (points from the top) down."""
    for i, line in enumerate(wrap(text, size)):
        if not line:
            continue
        obj = raw.FPDFPageObj_CreateTextObj(pdf, font, ctypes.c_float(size))
        buf = ctypes.create_string_buffer((line + "\0").encode("utf-16-le"))
        raw.FPDFText_SetText(obj, ctypes.cast(buf, ctypes.POINTER(raw.FPDF_WCHAR)))
        raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, LEFT, HEIGHT - (y + 1.075 * size + i * 1.374 * size))
        raw.FPDFPage_InsertObject(page.raw, obj)




class _Blocks(HTMLParser):
    """The page's text as blocks: ``("h", text)`` for a heading, ``("p", text)`` for anything else."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self._kind, self._text, self._skip = "p", [], 0

    def _flush(self) -> None:
        text = " ".join("".join(self._text).split())
        if text:
            self.blocks.append((self._kind, text))
        self._kind, self._text = "p", []

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "head", "title"):
            self._skip += 1
        elif tag in ("h1", "h2", "h3"):
            self._flush()
            self._kind = "h"
        elif tag in ("p", "div", "header", "ul", "ol"):
            self._flush()
        elif tag == "li":
            self._flush()
            self._text.append("\u2022 ")
        elif tag == "br":
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("style", "head", "title"):
            self._skip = max(self._skip - 1, 0)
        elif tag in ("h1", "h2", "h3", "p", "div", "header", "ul", "ol", "li"):
            self._flush()

    def handle_data(self, data):
        if not self._skip:
            self._text.append(data)


def blocks_of(html: str) -> list[tuple[str, str]]:
    parser = _Blocks()
    parser.feed(html)
    parser.close()
    parser._flush()
    return parser.blocks


def render(blocks: list[tuple[str, str]], out_pdf: Path) -> None:
    pdf = pdfium.PdfDocument.new()
    font = raw.FPDFText_LoadStandardFont(pdf, b"Helvetica")
    pages = [pdf.new_page(WIDTH, HEIGHT)]
    y = float(TOP)
    for kind, text in blocks:
        size = 14 if kind == "h" else 10
        while True:
            if y + needed(text, size) <= BOTTOM:
                place(pdf, font, pages[-1], text, size, y)
                y += needed(text, size) + (10 if kind == "h" else 8)
                break
            if y == TOP:  # longer than a whole page: set what fits, the rest goes on the next one
                words = text.split()
                first, text = " ".join(words[: len(words) // 2]), " ".join(words[len(words) // 2:])
                if TOP + needed(first, size) <= BOTTOM:
                    place(pdf, font, pages[-1], first, size, y)
            # did not fit: the next page, and the text again from there
            pages.append(pdf.new_page(WIDTH, HEIGHT))
            y = float(TOP)
    for page in pages:
        raw.FPDFPage_GenerateContent(page.raw)
    pdf.save(str(out_pdf))


def print_html(folder, html, out_pdf, *, entry="index.html", assets=None, timeout=60.0, launcher=None) -> None:
    """`html_pdf.print_html`, in the world: the page's text laid out in a PDF, or a failure for `worldfail`."""
    from door.tailoring import html_pdf

    if "worldfail" in html:
        raise html_pdf.PrintError("Chromium could not print the page: worldfail")
    render(blocks_of(html), Path(out_pdf))


def install() -> None:
    """Put the stand-in where door's print and Chromium lookup are."""
    from door.core import chromium
    from door.tailoring import html_pdf

    html_pdf.print_html = print_html
    chromium.find_chromium = lambda home=None: shutil.which("chrome-headless-shell") or sys.executable


if __name__ == "__main__":  # `chrome-headless-shell --version`, as `doctor` runs it
    if sys.argv[2:3] == ["--version"]:
        print("Chromium 157.0 (the test world's stand-in)")
        sys.exit(0)
    sys.stderr.write("the test world's chrome-headless-shell only answers --version\n")
    sys.exit(2)
