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


def problems(text: str, *, name: str | None, headings: list[str], keywords: list[str], pages: int = 1,
             side: list[str] | tuple[str, ...] = ()) -> list[dict]:
    """What would not survive an ATS reading `text` (a PDF's extracted text), as ``[{kind, detail}]``.

    Kinds: ``empty`` (under `MIN_CHARS_PER_PAGE` characters a page), ``garbled`` (replacement or private-use
    glyphs), ``missing`` (the name, a heading or a keyword absent), ``glued`` (a heading present but not on its
    own line), ``order`` (headings out of the order the source has them). No ``headings``: no heading checks.
    `side` are the headings of a side column: a reader may take that column before or after the main one and
    set its headings on a line of the main text, so they are checked for ``missing`` and for their order among
    themselves, never for ``glued`` or against the main headings.
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
    for column, glue in ((headings, True), (side, False)):
        positions: list[tuple[str, int]] = []
        for heading in column:
            wanted = normalise(heading)
            if not wanted:
                continue
            if wanted in lines:
                positions.append((heading, lines.index(wanted)))
            elif wanted not in flat:
                found.append({"kind": "missing", "detail": f"heading \"{heading}\" is not in the text"})
            elif glue:
                found.append({"kind": "glued", "detail": f"heading \"{heading}\" is not on a line of its own"})
        for (_, before), (later, after) in zip(positions, positions[1:]):
            if after < before:
                found.append({"kind": "order", "detail": f"heading \"{later}\" reads before an earlier section"})
                break
    for keyword in keywords:
        if normalise(keyword) and normalise(keyword) not in flat:
            found.append({"kind": "missing", "detail": f"keyword \"{keyword}\" is not in the text"})
    return found


# The kinds a second tailor run can fix by rewriting the text (the name, a heading or a keyword absent, or text that
# ran off the page or a CV over its page limit, which a shorter CV cures); the others are reported and not retried.
FIXABLE = {"missing", "overflow", "pages"}


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
SPARSE_SHARE = 0.2  # a last page with less ink than this share of the page height is sparse
MISSING_NAMED = 5  # how many absent words an `overflow` detail names


def squash(text: str) -> str:
    """`text` as letters and digits only (`normalise` first): what is left to compare when a PDF breaks a line or a word."""
    return "".join(c for c in normalise(text) if c.isalnum())


def overflow_problems(pdf_text: str, body: str) -> list[dict]:
    """``overflow``: words of the CV's HTML `body` (`html_doc.text`) that never reached the PDF's text, because Chromium
    cuts what runs past a page or its margin. Each word, squashed, must occur in the squashed `pdf_text` (unordered, no
    counts); one problem naming the first few that do not."""
    flat = squash(pdf_text)
    absent = [w for w in html_doc.text(body).split() if (key := squash(w)) and key not in flat]
    if not absent:
        return []
    return [{"kind": "overflow", "detail": f"text cut off: {', '.join(absent[:MISSING_NAMED])}"}]


def layout_problems(pages: list[tuple[float, float, list[Box]]], *, two_column: bool) -> list[dict]:
    """``sparse``: the last of several pages of a `two_column` CV holds no ink or under a fifth of the page height
    (reported only). `pages` is ``[(width, height, [char box (l, b, r, t)])]``, `pdf_render.page_boxes`."""
    if not two_column or len(pages) < 2:
        return []
    _, height, boxes = pages[-1]
    if not boxes or max(t for *_, t in boxes) - min(b for _, b, _, _ in boxes) < SPARSE_SHARE * height:
        return [{"kind": "sparse", "detail": f"the last page ({len(pages)}) is almost empty"}]
    return []


def page_problems(pages: int, max_pages: int | None) -> list[dict]:
    """``pages``: a CV of more pages than `max_pages` (`common._cv_max_pages`, the stricter of the country's and the
    template's), the limit named so the tailor's retry knows what to cut to (#194). No limit: nothing."""
    if max_pages is None or pages <= max_pages:
        return []
    return [{"kind": "pages", "detail": f"{pages} pages, over the limit of {max_pages} page{'s' if max_pages > 1 else ''}"}]


def check_pdf(pdf: Path, body: str, name: object, *, cv: bool = False, max_pages: int | None = None) -> list[dict]:
    """`problems` for `pdf`, with the headings and keywords taken from the HTML `body` it was printed from (`name`:
    the raw config's value, used when it is a string). A `cv` is also checked for words lost off the page
    (`overflow_problems`, unless no text could be read), for more pages than `max_pages` (`page_problems`) and,
    when `body` is placed in columns (the `side` div `compile._place_columns` adds only for a template with a side
    column), for a sparse last page (`layout_problems`); a letter gets none of these."""
    from door.tailoring import pdf_render

    text, pages = extract(pdf)
    cols = html_doc.columns(body)
    main, side = (body, "") if cols is None else (cols[0] + cols[1], cols[2])
    found = problems(text, name=name if isinstance(name, str) else None,
                     headings=html_doc.headings(main), side=html_doc.headings(side),
                     keywords=html_doc.keywords(body), pages=pages)
    if cv:
        if not {"empty", "garbled"} & {p["kind"] for p in found}:
            found += overflow_problems(text, body)
        found += page_problems(pages, max_pages)
        found += layout_problems(pdf_render.page_boxes(pdf), two_column=cols is not None)
    return found
