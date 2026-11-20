"""One reading of a prepared cv.html / cover_letter.html body (#146): its section headings, its notes, its text.

`readability`, `revise` and the `show` tool all read the body through here, so a heading, a note or a word
is the same thing for each. The body is the guarded fragment of `html_guard` (the tailor writes `<h2>` for a section,
`<!-- Keywords: ... -->` and `<!-- Tailoring: ... -->` as comments), with the `<<photo>>`-style tokens possibly in it.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from door.render import html_guard

_BLOCKS = frozenset({"header", "h1", "h2", "h3", "p", "ul", "ol", "li", "div", "br"})


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.headings: list[str] = []
        self.h3s: list[str] = []
        self.kinds: list[str | None] = []
        self.comments: list[str] = []
        self._cur: dict[str, list[str]] = {}

    def _emit(self, text: str) -> None:
        self.out.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCKS:
            self._emit("\n")
        elif tag == "span":  # the template sets the details apart; as text they are words apart
            self._emit(" ")
        if tag in ("h2", "h3"):
            self._cur[tag] = []
        if tag == "h2":
            self.kinds.append(next((c[len(html_guard.KIND_PREFIX):] for c in dict(attrs).get("class", "").split() if c.startswith(html_guard.KIND_PREFIX)), None))

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

    def handle_data(self, data):
        data = re.sub(r"\s+", " ", data.replace("\xa0", " "))
        for parts in self._cur.values():
            parts.append(data)
        self._emit(data)

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


def kinds(body: str) -> list[str | None]:
    """The kind of each `<h2>` of `body`, in order: the `kind-<kind>` class it carries, None for one with none."""
    return _read(body).kinds


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


def h3s(body: str) -> list[str]:
    """The `<h3>` texts of `body` (a CV's entry headings: ``Role | Company - dates``), in order."""
    return _read(body).h3s


def word_count(body: str) -> int:
    """The words of the text of `body` (a run of letters or digits, an apostrophe inside it kept)."""
    return len(re.findall(r"\w+(?:['’]\w+)*", text(body)))
