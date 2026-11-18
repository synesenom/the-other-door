"""One reading of a prepared cv.html / cover_letter.html body (#146): its section headings, its notes, its text.

`readability`, `facts`, `revise` and the `show` tool all read the body through here, so a heading, a note or a word
is the same thing for each. The body is the guarded fragment of `html_guard` (the tailor writes `<h2>` for a section,
`<!-- Keywords: ... -->` and `<!-- Tailoring: ... -->` as comments), with the `<<photo>>`-style tokens possibly in it.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from door.render import html_guard

_BLOCKS = frozenset({"header", "h1", "h2", "h3", "p", "ul", "ol", "li", "div", "br"})
# What is not the candidate's claims: the name (h1), the contact details, the recipient's address, the date, the
# sign-off. A header's tagline is (#189).
_NOT_CLAIMS_CLASSES = frozenset({"contact", "recipient", "date", "closing"})
SECTION = "\x00SECTION "
MAIN, SIDE = '<div class="main">', '<div class="side">'  # the two columns `compile._place_columns` wraps a CV in


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.claims: list[str] = []   # `out` without what is not a claim, an h2 as a section marker
        self.headings: list[str] = []
        self.h3s: list[str] = []
        self.comments: list[str] = []
        self._cur: dict[str, list[str]] = {}
        self._skip: tuple[str, int] | None = None   # (tag, nesting) of the element being left out of the claims

    def _emit(self, text: str, *, claim: bool = True) -> None:
        """Text into `out`, and into `claims` unless it is not the candidate's."""
        self.out.append(text)
        if claim:
            self.claims.append(text)

    def handle_starttag(self, tag, attrs):
        classes = set(dict(attrs).get("class", "").split())
        if self._skip is not None:
            if tag == self._skip[0] and tag != "br":
                self._skip = (tag, self._skip[1] + 1)
        elif tag == "h1" or classes & _NOT_CLAIMS_CLASSES:
            self._skip = (tag, 1)
        if tag in _BLOCKS:
            self._emit("\n")
        elif tag == "span":  # the template sets the details apart; as text they are words apart
            self._emit(" ")
        if tag in ("h2", "h3"):
            self._cur[tag] = []

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCKS:
            self._emit("\n")

    def handle_endtag(self, tag):
        if tag in _BLOCKS:
            self._emit("\n")
        elif tag == "span":
            self._emit(" ")
        for name, found in (("h2", self.headings), ("h3", self.h3s)):
            if tag == name and name in self._cur:
                heading = " ".join("".join(self._cur.pop(name)).split())
                if heading:
                    found.append(heading)
                    if name == "h2" and self._skip is None:
                        self.claims.append(f"\n{SECTION}{heading}\n")
        if self._skip is not None and tag == self._skip[0]:
            depth = self._skip[1] - 1
            self._skip = (tag, depth) if depth else None

    def handle_data(self, data):
        data = re.sub(r"\s+", " ", data.replace("\xa0", " "))
        for parts in self._cur.values():
            parts.append(data)
        self._emit(data, claim=self._skip is None and "h2" not in self._cur)

    def handle_comment(self, data):
        self.comments.append(data)


def _read(body: str) -> _Reader:
    reader = _Reader()
    reader.feed(html_guard.TOKENS.sub("", body))
    reader.close()
    return reader


def headings(body: str) -> list[str]:
    """The `<h2>` texts of `body`, in order (entities decoded, inner tags dropped, whitespace collapsed)."""
    return _read(body).headings


def columns(body: str) -> tuple[str, str, str] | None:
    """A CV `body` as `compile._place_columns` placed it, in its parts: what comes before the columns (the header), the
    main column and the side column; None for a body not placed in columns."""
    before, found, side = body.partition(SIDE)
    if not found:
        return None
    head, _, main = before.partition(MAIN)
    return head, main.removesuffix("</div>"), side.removesuffix("</div>")


def note(body: str, label: str) -> str | None:
    """The text of the `<!-- label: ... -->` comment of `body`, or None when it has none."""
    for comment in _read(body).comments:
        match = re.fullmatch(r"\s*" + re.escape(label) + r":\s*(.*?)\s*", comment, re.S)
        if match:
            return match.group(1)
    return None


def keywords(body: str) -> list[str]:
    """The keywords of the `Keywords` note, or []."""
    text = note(body, "Keywords")
    return [k.strip() for k in text.split(",") if k.strip()] if text else []


def text(body: str) -> str:
    """The text of `body` as a reader sees it: tags, comments and tokens dropped, entities decoded, each block (a
    paragraph, a heading, a list item, a `<br>`) on a line of its own."""
    lines = ("".join(_read(body).out)).splitlines()
    return "\n".join(" ".join(line.split()) for line in lines if line.strip())


def claim_text(body: str) -> str:
    """The text of `body` that holds the candidate's claims, for the facts check: `text` without the header (the
    contact details), the recipient, the date and the closing, each `<h2>` a ``SECTION <heading>`` line of its own."""
    lines = ("".join(_read(body).claims)).splitlines()
    return "\n".join(line if line.startswith(SECTION) else " ".join(line.split()) for line in lines if line.strip())


def h3s(body: str) -> list[str]:
    """The `<h3>` texts of `body` (a CV's entry headings: ``Role | Company - dates``), in order."""
    return _read(body).h3s


def word_count(body: str) -> int:
    """The words of the text of `body` (a run of letters or digits, an apostrophe inside it kept)."""
    return len(re.findall(r"\w+(?:['’]\w+)*", text(body)))
