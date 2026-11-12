"""Read a compiled CV or letter back the way an ATS does (#357): extract the PDF's text and check that the
name, the section headings (each on its own line, in order) and the keywords come out, and that the text is
neither garbled nor empty. Pure apart from reading the PDF (pypdfium2); no model call. Reported, never blocking."""

import re
import unicodedata
from pathlib import Path

# The `% Keywords: a, b` line the tailor writes into cv.tex (shared with `matches._materials`).
KEYWORDS_RE = re.compile(r"^\s*%\s*Keywords:\s*(.+?)\s*$", re.MULTILINE)
MIN_CHARS_PER_PAGE = 30
_SECTION_RE = re.compile(r"\\section\*?\s*\{((?:[^{}]|\{[^{}]*\})*)\}")
_COMMAND_RE = re.compile(r"\\[A-Za-z@]+\*?")
_ESCAPES = re.compile(r"\\([&%$#_{}])")
_PRIVATE_USE = re.compile("[\ue000-\uf8ff]")


def normalise(text: str) -> str:
    """`text` as comparable words: LaTeX commands and braces dropped, escapes undone, compatibility forms
    (ligatures) folded, case folded, whitespace collapsed."""
    text = _ESCAPES.sub(r"\1", text)
    text = _COMMAND_RE.sub(" ", text).replace("{", " ").replace("}", " ").replace("~", " ")
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(text.split())


def headings_from_tex(tex: str) -> list[str]:
    """The `\\section{...}` titles of a LaTeX source, in order."""
    return [m.group(1).strip() for m in _SECTION_RE.finditer(tex) if m.group(1).strip()]


def keywords_from_tex(tex: str) -> list[str]:
    """The keywords of the `% Keywords:` line, or []."""
    match = KEYWORDS_RE.search(tex)
    return [k.strip() for k in match.group(1).split(",") if k.strip()] if match else []


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


def extract(pdf: Path) -> tuple[str, int]:
    """The text of every page of `pdf` and its page count.

    Raises:
        Exception: the file is missing or not a readable PDF (pypdfium2's own error).
    """
    from door.tailoring import pdf_render

    texts = pdf_render.page_texts(pdf)
    return "\n".join(texts), len(texts)


def check_pdf(pdf: Path, tex: str, name: str | None) -> list[dict]:
    """`problems` for `pdf`, with the headings and keywords taken from its LaTeX source `tex`."""
    text, pages = extract(pdf)
    return problems(text, name=name, headings=headings_from_tex(tex), keywords=keywords_from_tex(tex), pages=pages)
