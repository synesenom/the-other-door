"""Read a compiled CV or letter back the way an ATS does (#357): extract the PDF's text and check that the
name, the section headings (each on its own line, in order) and the keywords come out, and that the text is
neither garbled nor empty. Pure apart from reading the PDF (pypdfium2); no model call. Reported, never blocking."""

import re
import unicodedata
from pathlib import Path

from door.tailoring import html_doc

MIN_CHARS_PER_PAGE = 30
_PRIVATE_USE = re.compile("[\ue000-\uf8ff]")


def normalise(text: str) -> str:
    """`text` as comparable words: compatibility forms (ligatures) folded, case folded, whitespace collapsed (a
    no-break space, `\u202f` among them, is whitespace)."""
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(text.split())


def problems(text: str, *, name: str | None, headings: list[str], keywords: list[str], pages: int = 1) -> list[dict]:
    """What would not survive an ATS reading `text` (a PDF's extracted text), as ``[{kind, detail}]``.

    Kinds: ``empty`` (under `MIN_CHARS_PER_PAGE` characters a page), ``garbled`` (replacement or private-use
    glyphs), ``missing`` (the name, a heading or a keyword absent), ``glued`` (a heading present but not on its
    own line), ``order`` (headings out of the order the source has them). No ``headings``: no heading checks.
    """
    found: list[dict] = []
    if len("".join(text.split())) < MIN_CHARS_PER_PAGE * max(pages, 1):
        found.append({"kind": "empty", "detail": "almost no text could be read from the PDF"})
    if "\ufffd" in text or _PRIVATE_USE.search(text):
        found.append({"kind": "garbled", "detail": "some characters read back as unmapped glyphs"})
    flat = normalise(text)
    if name and normalise(name) not in flat:
        found.append({"kind": "missing", "detail": f"your name ({name}) is not in the text"})
    lines = [normalise(line) for line in text.splitlines()]
    positions: list[tuple[str, int]] = []
    for heading in headings:
        wanted = normalise(heading)
        if not wanted:
            continue
        if wanted in lines:
            positions.append((heading, lines.index(wanted)))
        elif wanted in flat:
            found.append({"kind": "glued", "detail": f"heading \"{heading}\" is not on a line of its own"})
        else:
            found.append({"kind": "missing", "detail": f"heading \"{heading}\" is not in the text"})
    for (_, before), (later, after) in zip(positions, positions[1:]):
        if after < before:
            found.append({"kind": "order", "detail": f"heading \"{later}\" reads before an earlier section"})
            break
    for keyword in keywords:
        if normalise(keyword) and normalise(keyword) not in flat:
            found.append({"kind": "missing", "detail": f"keyword \"{keyword}\" is not in the text"})
    return found


# The kinds a second tailor run can fix by rewriting the text (the name, a heading or a keyword absent, or text that
# ran off the page, which a shorter CV cures); the others are reported and not retried.
FIXABLE = {"missing", "overflow"}


def fixable(found: list[dict]) -> list[dict]:
    """The problems of `found` (``[{kind, detail, ...}]``) whose kind is in `FIXABLE`."""
    return [p for p in found if p.get("kind") in FIXABLE]


def extract(pdf: Path) -> tuple[str, int]:
    """The text of every page of `pdf` and its page count.

    Raises:
        Exception: the file is missing or not a readable PDF (pypdfium2's own error).
    """
    from door.tailoring import pdf_render

    texts = pdf_render.page_texts(pdf)
    return "\n".join(texts), len(texts)


Box = tuple[float, float, float, float]
Margins = tuple[float, float, float, float]  # top, right, bottom, left, in points
_SLACK = 0.5  # points a character may stand past the content box before it counts (rounding of glyph boxes); Chromium
# clips what runs past the page or its margin, so a glyph straddling the edge is all of the overflow a PDF keeps
SPARSE_SHARE = 0.2  # a last page with less ink than this share of the content height is sparse


def layout_problems(pages: list[tuple[float, float, list[Box]]], *, margins: Margins, two_column: bool) -> list[dict]:
    """What the page geometry of a CV shows: `pages` is ``[(width, height, [char box (l, b, r, t)])]`` (points, origin
    bottom-left, `pdf_render.page_boxes`), `margins` the template's ``@page`` margins (top, right, bottom, left).

    ``overflow``: a character past the left or right margin, below the bottom margin or off the page (once, naming
    the first page), told to the tailor as a cut to make; ``sparse``: the last of several pages of a `two_column` CV
    holds ink under a fifth of the content height (reported only).
    """
    top, right, bottom, left = margins
    found: list[dict] = []
    for number, (width, height, boxes) in enumerate(pages, 1):
        if any(l < left - _SLACK or r > width - right + _SLACK or b < bottom - _SLACK or t > height + _SLACK
               for l, b, r, t in boxes):
            found.append({"kind": "overflow", "detail": (
                f"text on page {number} runs past the page margin; trim the lowest-value items so it fits, "
                "never invent anything")})
            break
    if two_column and len(pages) > 1:
        _, height, boxes = pages[-1]
        content = height - top - bottom
        if boxes and content > 0:
            ink = max(t for *_, t in boxes) - min(b for _, b, _, _ in boxes)
            if ink < SPARSE_SHARE * content:
                found.append({"kind": "sparse", "detail": f"the last page ({len(pages)}) is almost empty"})
    return found


def check_pdf(pdf: Path, body: str, name: object, *, margins: Margins | None = None, two_column: bool = False) -> list[dict]:
    """`problems` for `pdf`, with the headings and keywords taken from the HTML `body` it was printed from (`name`:
    the raw config's value, used when it is a string). With `margins` (a CV: the template's page margins) the page
    geometry is checked too (`layout_problems`); without, it is not (a letter)."""
    from door.tailoring import pdf_render

    text, pages = extract(pdf)
    found = problems(text, name=name if isinstance(name, str) else None,
                     headings=html_doc.headings(body),
                     keywords=html_doc.keywords(body), pages=pages)
    if margins is not None:
        found += layout_problems(pdf_render.page_boxes(pdf), margins=margins, two_column=two_column)
    return found
