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

from door.tailoring import style_icons

TAGS = frozenset({"header", "h1", "h2", "h3", "p", "ul", "ol", "li", "div", "span", "strong", "em", "a", "br"})
VOID = frozenset({"br"})
# What the template's CSS styles; `photo`, `main` and `side` are written by `compile` after the guard, never by the model.
CLASSES = frozenset({
    "cv-header", "contact", "entry", "letter-header", "recipient", "date", "closing", "signoff",
    "tagline", "phone", "email", "web", "location", "linkedin", "github",
    "role", "org", "dates", "place", "sep", "level", "level-1", "level-2", "level-3", "level-4", "level-5",
})
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


# ---------- a built template (#204) ----------
#
# A CV template built from an uploaded CV is a page a model wrote around the `<<body>>` token: the `<head>`, the CSS and
# the structure. The sealed browser prints it, so before it is printed it is read here: no script, link, picture or
# frame, nothing loaded but the manifest's fonts and icons, the two tokens once each, the rules `compile` and the tailor
# rely on. Not called by `compile`: a template in `profile/` is the user's own.

_TEMPLATE_TAGS = TAGS | {"html", "head", "meta", "title", "style", "body"}
_TEMPLATE_ATTRS = {"class", "lang", "style"}
_META_ATTRS = {"charset", "name", "content"}  # no http-equiv: a <meta> may not refresh or redirect
_TEMPLATE_TOKEN = re.compile(r"<<(\w*)>>")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_CSS_COMMENT = re.compile(r"/\*.*?(?:\*/|$)", re.S)
_CSS_STRING = re.compile(r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'")
_CSS_URL = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)\"'\s]*))\s*\)", re.I)
_CSS_LOADERS = re.compile(r"@import|url\(|attr\(|image-set\(|(?<![\w-])image\(|cross-fade\(|element\(|paint\(|(?<![\w-])src\(|"
                          r"expression\(|-moz-binding|behavior\s*:", re.I)
_CSS_CONTENT = re.compile(r"(?<![\w-])content\s*:([^;}]*)", re.I)
# what a `content:` string may print: a list bullet or a separator, never text or a glyph standing for an icon (#248)
_CONTENT_MARKS = frozenset(style_icons.BULLETS | set("—|/.,"))
_CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})\s?|\r?\n|(.))", re.S)


def _unescape_css(text: str) -> str:
    """`text` (the inside of a CSS string) with its escapes decoded: `\\4A` is J."""
    def char(m):
        if m.group(1):
            code = int(m.group(1), 16)
            return chr(code) if 0 < code <= 0x10FFFF else "\ufffd"
        return m.group(2) or ""
    return _CSS_ESCAPE.sub(char, text)
# the classes the shipped templates' header comment lists, by what the tailor writes in each kind of page
_LEVELS = frozenset(f"level-{n}" for n in range(1, 6))
_LETTER_ONLY = frozenset({"letter-header", "recipient", "date", "closing", "signoff"})
_CV_ONLY = frozenset({"cv-header", "entry", "tagline", "role", "org", "dates", "place", "sep", "level"})
_COMMENT_CLASSES = {"cv": sorted(CLASSES - _LETTER_ONLY - _LEVELS | {"level"}), "letter": sorted(CLASSES - _CV_ONLY - _LEVELS)}
_BODY_MARK = "\x01"  # stands for <<body>> while the template is read: it must land in a text node of the page
_TOKEN_STANDINS = {"body": _BODY_MARK, "lang": "en"}  # the template's two tokens, and what each is read as


class _TemplateReader(_Reader):
    def __init__(self) -> None:
        super().__init__()
        self.css: list[str] = []
        self.comments: list[str] = []
        self.text: list[str] = []
        self.style_openers = 0
        self._in = []  # open style/title elements

    def _tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.events += 1
        if tag not in _TEMPLATE_TAGS:
            self.found.append(f"<{tag}>")
        allowed = _META_ATTRS if tag == "meta" else _TEMPLATE_ATTRS
        for name, value in attrs:
            if _BODY_MARK in (value or ""):
                self.found.append("<<body>> inside an attribute")
            if name not in allowed:
                self.found.append(f"{name}= on <{tag}>")
            elif name == "style":
                self.css.append(value or "")

    def handle_starttag(self, tag, attrs):
        self._tag(tag, attrs)
        if tag in ("style", "title"):
            self._in.append(tag)

    def handle_startendtag(self, tag, attrs):
        self._tag(tag, attrs)

    def handle_endtag(self, tag):
        self.events += 1
        if tag not in _TEMPLATE_TAGS or tag in VOID:
            self.found.append(f"</{tag}>")
        if self._in and self._in[-1] == tag:
            self._in.pop()

    def handle_data(self, data):
        if _BODY_MARK in data and self._in:
            self.found.append(f"<<body>> inside <{self._in[-1]}>")
        data = data.replace(_BODY_MARK, "")
        if self._in and self._in[-1] == "style":
            self.css.append(data)
            self.style_openers += len(_OPENER.findall(data))
        elif not self._in and data.strip():
            self.text.append(data.strip())

    def handle_comment(self, data):
        self.events += 1
        self.comments.append(data)

    def handle_decl(self, decl):
        self.events += 1
        if decl.strip().lower() != "doctype html":
            self.found.append(f"<!{_head_word(decl)}>")


def _css_problems(css: str, manifest) -> list[str]:
    found: list[str] = []
    css = _CSS_COMMENT.sub("", css)
    fonts = manifest.fonts if manifest else []
    icons = list(manifest.icons.values()) if manifest else []
    for m in _CSS_URL.finditer(css):
        target = next(g for g in m.groups() if g is not None).strip()
        folder, _, name = target.rpartition("/")
        if not ((folder == "/fonts" and name in fonts) or (folder == "/icons" and name in icons)):
            found.append(f"url({target[:60]}) (only /fonts/ and /icons/ files template.json names)")
    for m in _CSS_CONTENT.finditer(css):  # text a rule bakes into the page is not the CV's: it would print on every one
        if any(not (c.isspace() or c in _CONTENT_MARKS) for string in _CSS_STRING.findall(m.group(1))
               for c in _unescape_css(string[1:-1])):
            found.append(f"content: may hold only spaces, bullets and separators ({''.join(sorted(_CONTENT_MARKS))}): text "
                         "belongs in the CV, an icon in an /icons/ file (#248)")
    stripped = _CSS_URL.sub("", _CSS_STRING.sub('""', css))
    for m in _CSS_LOADERS.finditer(stripped):
        word = m.group(0).lower()
        found.append(word + ")" if word.endswith("(") else word)
    if "\\" in stripped:
        found.append("a CSS escape outside a string")
    return found


def template_problems(html: str, manifest, kind: str = "cv") -> list[str]:
    """What a built `kind` ("cv" or "letter") template holds that it may not, in order, each once (`[]` when clean).

    `manifest` is its `template.json` (`templates.Manifest`, or None for no fonts or icons). Refused: a script, link,
    picture, SVG, frame, object, form, `<base>` or refreshing `<meta>`, an `on*`, `src`, `href`, `srcset` or similar
    attribute, an `@import` or image function in CSS, a CSS escape outside a string, a `url()` other than
    `/fonts/<file in manifest.fonts>` or `/icons/<file in manifest.icons>`, a markup a browser could read differently,
    visible text outside the tokens. Required: exactly one `<<body>>` and one `<<lang>>` and no other token, a rule for
    `.photo` (a CV only: a letter has no photo), `font-synthesis: none`, and a first comment naming the classes of
    the vocabulary (the CV's, or the letter's) that the tailor writes, as the shipped templates' header does.
    """
    found: list[str] = []
    visible = _HTML_COMMENT.sub("<!---->", html)  # the header comment documents the tokens and the tags
    tokens = [m.group(1) for m in _TEMPLATE_TOKEN.finditer(visible)]
    for name in _TOKEN_STANDINS:
        if tokens.count(name) != 1:
            found.append(f"<<{name}>> must be there exactly once (found {tokens.count(name)})")
    found += [f"<<{t}>> (the body's tokens are not the template's)" for t in dict.fromkeys(tokens) if t not in _TOKEN_STANDINS]
    text = _TEMPLATE_TOKEN.sub(lambda m: _TOKEN_STANDINS.get(m.group(1), ""), html)
    counted = _TEMPLATE_TOKEN.sub("", visible)
    parser = _TemplateReader()
    parser.feed(text)
    parser.close()
    found += parser.found
    css = "\n".join(parser.css)
    found += _css_problems(css, manifest)
    if len(_OPENER.findall(counted)) - parser.style_openers != parser.events or text.count("<!--") != text.count("-->"):
        found.append("markup a browser could read differently (an unclosed tag or comment)")
    if parser.text:
        found.append(f"text outside the tokens: {parser.text[0][:40]!r}")
    plain = _CSS_COMMENT.sub("", css)
    if kind == "cv" and not re.search(r"\.photo(?![\w-])", plain):
        found.append("no .photo rule (a template without one prints no photo)")
    if not re.search(r"font-synthesis\s*:\s*none", plain, re.I):
        found.append("no font-synthesis: none")
    wanted = _COMMENT_CLASSES.get(kind, _COMMENT_CLASSES["cv"])
    header = parser.comments[0] if parser.comments else ""
    missing = [c for c in wanted if not re.search(rf"(?<![\w-]){re.escape(c)}(?![\w-])", header)]
    if not parser.comments:
        found.append("no header comment listing the vocabulary classes")
    elif missing:
        found.append("the header comment does not list the classes: " + ", ".join(missing))
    return list(dict.fromkeys(found))
