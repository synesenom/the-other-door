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

import html
import re
from html.parser import HTMLParser

from door.core import cv_read

TAGS = frozenset({"header", "h1", "h2", "h3", "p", "ul", "ol", "li", "div", "span", "strong", "em", "a", "br"})
VOID = frozenset({"br"})
# What the template's CSS styles; `photo` is written by `compile` after the guard, never by the model.
CLASSES = frozenset({
    "cv-header", "contact", "entry", "letter-header", "recipient", "date", "closing", "signoff",
    "tagline", "phone", "email", "web", "location", "linkedin", "github",
    "role", "org", "dates", "place", "sep", "level", "level-1", "level-2", "level-3", "level-4", "level-5",
})
# the kind of a CV section, on its `<h2>` only: the tailor writes it by what the section holds
KIND_PREFIX = "kind-"
KIND_CLASSES = frozenset(f"{KIND_PREFIX}{k}" for k in cv_read.KINDS)
NOTES = ("Keywords", "Tailoring")
TOKENS = re.compile(r"<<(?:photo|date|company|title)>>")
_OPENER = re.compile(r"<[A-Za-z/!?]")
_NOTE = re.compile(r"\s*(?:" + "|".join(NOTES) + r"):[^<>]*", re.S)
_LINK = re.compile(r"(?:https://[^\s/]|mailto:[^\s]|#[^\s]*$)", re.I)


def _head_word(text: str) -> str:
    """The first word of a declaration or processing instruction: what a refusal names."""
    return re.match(r"[^\s\[]*", text.strip()).group(0)


class _Reader(HTMLParser):
    """What `_Collector` and `_TemplateReader` share: every event counted, what is outside the vocabulary in `found`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[str] = []
        self.events = 0

    def _flag(self, what: str) -> None:
        self.found.append(what)

    def handle_pi(self, data):
        self.events += 1
        self._flag(f"<?{_head_word(data)}>")

    def unknown_decl(self, data):
        self.events += 1
        self._flag(f"<![{_head_word(data)}[")


class _Collector(_Reader):
    def _start(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.events += 1
        if tag not in TAGS:
            self._flag(f"<{tag}>")
            return
        for name, value in attrs:
            value = value or ""
            if "<" in value or ">" in value:
                self._flag(f"{name}= with a < or >")
            elif name == "class" and value.strip() and all(
                    c in CLASSES or (tag == "h2" and c in KIND_CLASSES) for c in value.split()):
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
        self._flag(f"<!{_head_word(decl)}>")


def unsafe(body: str) -> list[str]:
    """What `body` holds that is outside the vocabulary, in order, each once (`[]` when it is clean).

    The `<<photo>>`, `<<date>>`, `<<company>>` and `<<title>>` tokens are left out first: `compile` fills them.
    """
    text = TOKENS.sub("", body)
    parser = _Collector()
    parser.feed(text)
    parser.close()
    found = parser.found
    if len(_OPENER.findall(text)) != parser.events or text.count("<!--") != text.count("-->"):
        found = found + ["markup a browser could read differently (an unclosed tag or comment)"]
    return list(dict.fromkeys(found))


_A = re.compile(r"<a\b([^<>]*)>(.*?)</a\s*>", re.S | re.I)
_HREF = re.compile(r"""\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
_WORD = re.compile(r"[^\s()<>\[\]\"'|,;]+")


def _target(text: str) -> str:
    """A link target without its scheme, `www.` and trailing slashes, lower case: what two spellings of one address share."""
    t = html.unescape(text).strip().strip(".:").lower()
    t = re.sub(r"^(?:https?://|mailto:)", "", t)
    return re.sub(r"^www\.", "", t).rstrip("/")


def unwrap_unknown_links(body: str, sources: list[str]) -> str:
    """`body` with each `<a>` whose whole target is not written in one of `sources` (cv.md, the story bank) as its text.

    The tailor reads the ad and the profile, so an ad can steer it into a link target that carries what it read to a
    stranger: the target is the one part of the PDF nobody sees. The whole target is compared, scheme, `www.` and a
    trailing slash apart, so no data rides in a known host's path.
    """
    known = {_target(w) for text in sources for w in _WORD.findall(text)}

    def unwrap(match: re.Match) -> str:
        href = _HREF.search(match.group(1))
        target = _target(href.group(1) if href.group(1) is not None else href.group(2)) if href else ""
        return match.group(0) if target and target in known else match.group(2)

    return _A.sub(unwrap, body)
