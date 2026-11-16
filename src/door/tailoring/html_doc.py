"""One reading of a prepared cv.html / cover_letter.html body (#146): its section headings, its notes, its text.

`readability`, `facts`, `revise` and the `show` tool all read the body through here, so a heading, a note or a word
is the same thing for each. The body is the guarded fragment of `html_guard` (the tailor writes `<h2>` for a section,
`<!-- Keywords: ... -->` and `<!-- Tailoring: ... -->` as comments), with the `<<photo>>`-style tokens possibly in it.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_TOKENS = re.compile(r"<<(?:photo|date|company|title)>>")
_BLOCKS = frozenset({"header", "h1", "h2", "h3", "p", "ul", "ol", "li", "div", "br"})


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.headings: list[str] = []
        self.comments: list[str] = []
        self._h2: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCKS:
            self.out.append("\n")
        if tag == "h2":
            self._h2 = []

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag in _BLOCKS:
            self.out.append("\n")
        if tag == "h2" and self._h2 is not None:
            heading = " ".join("".join(self._h2).split())
            if heading:
                self.headings.append(heading)
            self._h2 = None

    def handle_data(self, data):
        data = data.replace("\xa0", " ")
        self.out.append(data)
        if self._h2 is not None:
            self._h2.append(data)

    def handle_comment(self, data):
        self.comments.append(data)


def _read(body: str) -> _Reader:
    reader = _Reader()
    reader.feed(_TOKENS.sub("", body))
    reader.close()
    return reader


def headings(body: str) -> list[str]:
    """The `<h2>` texts of `body`, in order (entities decoded, inner tags dropped, whitespace collapsed)."""
    return _read(body).headings


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


def word_count(body: str) -> int:
    """The words of the text of `body` (a run of letters or digits, an apostrophe inside it kept)."""
    return len(re.findall(r"\w+(?:['’]\w+)*", text(body)))
