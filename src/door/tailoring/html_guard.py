"""What a prepared cv.html / cover_letter.html may contain (#146, #302 hardening).

The two files are body fragments in a closed vocabulary: the template owns the `<head>`, the CSS, the fonts and the
page, and the model writes only headings, paragraphs, lists and links. The fragment is model output, steered by a job
ad (an untrusted page) or an instruction typed on a phone, and a real browser prints it, so the guard is an
allow-list: any tag, attribute, class, link, comment or declaration outside it is named, and `compile` refuses a body
it names anything in. The browser is sealed as well (scripts off, a server that serves only the job folder and the
fonts); this is the first layer, that the second.

Parsing is `html.parser` with character references decoded, so `&#106;avascript:` is read as `javascript:`. A `<`
that the parser and a browser could read differently (a quoted value holding one, a comment that is not closed) is
refused, and the count of markup openers must equal the count of tokens the parser saw.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

TAGS = frozenset({"header", "h1", "h2", "h3", "p", "ul", "ol", "li", "div", "span", "strong", "em", "a", "br"})
VOID = frozenset({"br"})
# What the template's CSS styles; `photo` is written by `compile` after the guard, never by the model.
CLASSES = frozenset({"cv-header", "contact", "entry", "letter-header", "recipient", "date", "closing", "signoff"})
NOTES = ("Keywords", "Tailoring")
_TOKENS = re.compile(r"<<(?:photo|date|company|title)>>")
_OPENER = re.compile(r"<[A-Za-z/!?]")
_NOTE = re.compile(r"\s*(?:" + "|".join(NOTES) + r"):[^<>]*", re.S)
_LINK = re.compile(r"(?:https://[^\s/]|mailto:[^\s]|#[^\s]*$)", re.I)


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[str] = []
        self.events = 0

    def _flag(self, what: str) -> None:
        self.found.append(what)

    def _start(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.events += 1
        if tag not in TAGS:
            self._flag(f"<{tag}>")
            return
        for name, value in attrs:
            value = value or ""
            if "<" in value or ">" in value:
                self._flag(f"{name}= with a < or >")
            elif name == "class" and all(c in CLASSES for c in value.split()) and value.strip():
                continue
            elif name == "href" and tag == "a" and _LINK.match(re.sub(r"[\x00-\x20]", "", value)):
                continue
            else:
                self._flag(f"{name}= on <{tag}>" if name in ("class", "href") else f"{name}=")

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs)

    def handle_endtag(self, tag):
        self.events += 1
        if tag not in TAGS or tag in VOID:
            self._flag(f"</{tag}>")

    def handle_comment(self, data):
        self.events += 1
        if not _NOTE.fullmatch(data):
            self._flag("a comment other than Keywords: or Tailoring:")

    def handle_decl(self, decl):
        self.events += 1
        self._flag("<!" + decl.split(None, 1)[0] + ">" if decl.split() else "<!>")

    def handle_pi(self, data):
        self.events += 1
        self._flag("<?" + data.split(None, 1)[0] + ">" if data.split() else "<?>")

    def unknown_decl(self, data):
        self.events += 1
        self._flag("<![" + data.split("[", 1)[0] + "[")


def unsafe(body: str) -> list[str]:
    """What `body` holds that is outside the vocabulary, in order, each once (`[]` when it is clean).

    The `<<photo>>`, `<<date>>`, `<<company>>` and `<<title>>` tokens are left out first: `compile` fills them.
    """
    text = _TOKENS.sub("", body)
    parser = _Collector()
    parser.feed(text)
    parser.close()
    found = parser.found
    if len(_OPENER.findall(text)) != parser.events or text.count("<!--") != text.count("-->"):
        found = found + ["markup a browser could read differently (an unclosed tag or comment)"]
    return list(dict.fromkeys(found))
