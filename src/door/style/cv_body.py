"""`profile/cv.md` as a body in the tailor's vocabulary, with no model (#204, epic #144).

`body(cv_md, lang)` is what the stress renders and the previews of a built CV template print: the same shapes the
tailor agent writes (`html_guard`'s tags and classes; `.claude/agents/tailor.md`'s building blocks), made from the
markdown that `draft_cv` and `init` write. Nothing is translated, tailored or dropped; text and links are escaped
and only `https:`, `mailto:` and `#` links are kept.

- `# Name` is the header's `<h1>`, a `> line` its tagline, the lines before the first `##` its contact details
  (`**Label:** value`, a plain `Label: value` and the other forms `_details` reads, split on `|`, the label in any
  supported language; a detail with no known label is a plain `<span>`, an `@` one is an email), written with a kind
  class in the template's order (phone, email, web, linkedin, github, location). The `<<photo>>` token comes first in the header, as the tailor writes it;
  `compile` swaps it. `header(cv_md)` is the same header as data, which `infer_basics` reads too (#208).
- `## Heading` is an `<h2>`, whatever it says (a heading the columns do not know stays in the main column).
- `### Role | Org — dates | Place` is an `<div class="entry">` whose `<h3>` has the parts in `role`, `org`, `dates` and
  `place` spans with `sep` spans between (` | `, ` - `, ` | `): a heading with no ` | ` is a role alone, and the dates
  split off at the first spaced em or en dash, else at the first spaced hyphen when a number follows it. Its bullets and paragraphs go inside it.
- `- item` is an `<li>` of a `<ul>`, `1. item` of an `<ol>`; other lines are a `<p>` (consecutive lines joined).
- A skill or language with a level, `**Danish** — conversational`, in a Skills or Languages section (the ad's language
  or English), gets `<span class="level level-N">` around the level word, by the tailor's table: native and C2 are 5;
  fluent, professional and C1, 4; working and B2, 3; conversational and B1, 2; basic, A1 and A2, 1. A word outside that
  table (in any language: the table is the tailor's, English and CEFR) gets no level class: a level is never guessed.
- No `<!-- Keywords -->` or `<!-- Tailoring -->` notes: this body is not tailored.
"""

from __future__ import annotations

import html
import re

from door import i18n
from door.core import cv_sections

_LEVELS = {"native": 5, "c2": 5, "fluent": 4, "professional": 4, "c1": 4, "working": 3, "b2": 3,
           "conversational": 2, "b1": 2, "basic": 1, "a1": 1, "a2": 1}
_LEVEL_SECTIONS = ("skills", "languages")
_SAFE_URL = re.compile(r"(?:https://|mailto:|#)[^\s<>\"']+$", re.I)
_INLINE = re.compile(r"\*\*(?P<b>.+?)\*\*|\*(?P<i>[^*\s][^*]*?)\*|\[(?P<t>[^\]]+)\]\((?P<u>(?:[^()\s]|\([^()\s]*\))+)\)")
_DASH_DATES = re.compile(r"\s+[—–]\s+")
_HYPHEN_DATES = re.compile(r"\s+-\s+(?=\S*\d)")
_LEVEL_ITEM = re.compile(r"^(?:\*\*(?P<bold>[^*]+?)\*\*|(?P<plain>[^—–:()*]+?))\s*(?:[—–:]|\()\s*(?P<word>[^()]+?)\)?\s*$")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")


def _inline(text: str) -> str:
    """`text` with `**bold**`, `*em*` and `[text](https://...)` as tags and everything else escaped."""
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        out.append(html.escape(text[pos:m.start()], quote=False))
        if m["b"] is not None:
            out.append(f"<strong>{_inline(m['b'])}</strong>")
        elif m["i"] is not None:
            out.append(f"<em>{_inline(m['i'])}</em>")
        elif _SAFE_URL.match(m["u"]):
            out.append(f'<a href="{html.escape(m["u"])}">{html.escape(m["t"], quote=False)}</a>')
        else:
            out.append(html.escape(m["t"], quote=False))
        pos = m.end()
    out.append(html.escape(text[pos:], quote=False))
    return "".join(out)


def _link(url: str) -> str:
    """`url` as a safe https link target (a bare address gets the scheme, http becomes https), or ''."""
    url = re.sub(r"^(?:https?://)?", "https://", url.strip(), count=1, flags=re.I)
    return url if _SAFE_URL.match(url) else ""


def _detail(kind: str | None, value: str) -> str:
    cls = f' class="{kind}"' if kind else ""
    plain = re.sub(r"\*\*|\[|\]\(.*?\)", "", value)  # a markdown link or bold in a detail: its text
    mail = re.fullmatch(r"(?:mailto:)?([^\s@<>\"']+@[^\s@<>\"']+)", plain)
    if mail and kind in ("email", None):
        address = html.escape(mail.group(1))
        return f'<span class="email"><a href="mailto:{address}">{address}</a></span>'
    if kind in ("web", "linkedin", "github"):
        href = _link(plain)
        if href:
            text = re.sub(r"^https://(?:www\.)?|/$", "", href) if kind == "web" else re.sub(r"^https://", "", href).rstrip("/")
            return f'<span{cls}><a href="{html.escape(href)}">{html.escape(text, quote=False)}</a></span>'
    return f"<span{cls}>{_inline(value)}</span>"


def _details(lines: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """The contact parts of `lines` (split on `|`): the values of the labelled ones by kind, and the parts with no
    known label whole. A label is one `i18n.contact_kind` knows, followed by a colon or a spaced dash, bold or not, the
    bold around the label or around the whole part, after any leading symbols: `**Location:** X`, `Location: X`,
    `**Location: X**`, `\ud83d\udccd Location: X`, `Location - X`. An empty value is dropped."""
    found: dict[str, list[str]] = {}
    other: list[str] = []
    for line in lines:
        for part in line.split("|"):
            part = part.strip()
            label = re.match(r"^(.+?)\s*(?::|\s[-\u2013\u2014]\s)\s*(.*)$", re.sub(r"^\W+", "", part.replace("**", "")))
            kind = i18n.contact_kind(label.group(1)) if label else None
            if kind:
                if value := label.group(2).strip(" :"):
                    found.setdefault(kind, []).append(value)
            elif part:
                other.append(part)
    return found, other


def header(cv_md: str) -> dict:
    """The CV's header as data: ``{"name", "details", "other"}``, `details` the contact values by kind (read in every
    supported language's labels) and `other` the parts with no known label; what `infer_basics` reads."""
    name, _, preamble = _header_parts(cv_md)
    details, other = _details(preamble)
    return {"name": name, "details": details, "other": other}


def _contact(lines: list[str]) -> str:
    found, other = _details(lines)
    spans = [_detail(kind, v) for kind in i18n.CONTACT_KINDS for v in found.get(kind, [])] + [_detail(None, p) for p in other]
    return f'<p class="contact">{"".join(spans)}</p>' if spans else ""


def _heading3(text: str) -> str:
    parts = [p.strip() for p in text.split(" | ")]
    sep = lambda s: f'<span class="sep">{s}</span>'  # noqa: E731
    span = lambda cls, v: f'<span class="{cls}">{_inline(v)}</span>'  # noqa: E731
    if len(parts) == 1:
        return f'<h3>{span("role", parts[0])}</h3>'
    org, dates = parts[1], None
    split = _DASH_DATES.search(org) or _HYPHEN_DATES.search(org)  # the first dash is the org's, the dates may hold more
    if split:
        org, dates = org[:split.start()], org[split.end():]
    out = [span("role", parts[0]), sep(" | "), span("org", org)]
    if dates:
        out += [sep(" - "), span("dates", dates)]
    if len(parts) > 2:
        out += [sep(" | "), span("place", " | ".join(parts[2:]))]
    return f"<h3>{''.join(out)}</h3>"


def _level_item(text: str) -> str | None:
    m = _LEVEL_ITEM.match(text.strip())
    if not m:
        return None
    word = m["word"].strip()
    number = _LEVELS.get(word.casefold())
    if number is None:
        return None
    name = m["bold"] or m["plain"].strip()
    return f'<li><strong>{_inline(name)}</strong> <span class="level level-{number}">{html.escape(word, quote=False)}</span></li>'


class _Blocks:
    """The body's blocks as `body` reads the lines: a paragraph or list is kept as text until it ends, and is built
    then, so a wrapped list item is whole before it is read for a level."""

    def __init__(self) -> None:
        self.out: list[str] = []
        self.entry = False
        self.levels = False  # in a skills or languages section
        self.para: list[str] = []
        self.tag = ""  # the open list's tag
        self.items: list[str] = []

    def flush(self) -> None:
        if self.para:
            self.out.append(f"<p>{_inline(' '.join(self.para))}</p>")
            self.para = []
        if self.items:
            built = [(_level_item(t) if self.levels else None) or f"<li>{_inline(t)}</li>" for t in self.items]
            self.out.append(f"<{self.tag}>{''.join(built)}</{self.tag}>")
            self.items = []

    def close_entry(self) -> None:
        self.flush()
        if self.entry:
            self.out[-1] += "</div>"
            self.entry = False

    def item(self, tag: str, text: str) -> None:
        if self.para or (self.items and self.tag != tag):
            self.flush()
        self.tag = tag
        self.items.append(text)


def _header_parts(cv_md: str) -> tuple[str | None, str | None, list[str]]:
    """What is above the first `## ` heading: the name (`# `), the tagline (the first `>` line) and the contact lines."""
    name = tagline = None
    preamble: list[str] = []
    for raw in cv_md.splitlines():
        stripped = raw.strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith("# ") and name is None:
            name = stripped[2:].strip()
        elif stripped.startswith(">"):
            tagline = tagline or stripped.lstrip("> ").strip() or None
        elif stripped and not stripped.startswith("#"):
            preamble.append(stripped)
    return name, tagline, preamble


def body(cv_md: str, lang: str = "en") -> str:
    """The CV in `cv_md` as a body (see the module's docstring); '' for a CV with nothing in it. `lang` is the ad's
    language, which reads the section headings that tell a skills or languages list (levels)."""
    name, tagline, preamble = _header_parts(cv_md)
    blocks = _Blocks()
    in_header = True
    for raw in cv_md.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("## "):
            in_header = False
            blocks.close_entry()
            heading = cv_sections.heading(stripped)[0]
            blocks.levels = cv_sections.kind([stripped], _LEVEL_SECTIONS, (lang, "en")) is not None
            blocks.out.append(f"<h2>{_inline(heading)}</h2>")
        elif in_header:
            continue
        elif stripped.startswith("### "):
            blocks.close_entry()
            blocks.out.append(f'<div class="entry">{_heading3(stripped[4:].strip())}')
            blocks.entry = True
        elif not stripped:
            blocks.flush()
        elif item := _ITEM.match(line):
            blocks.item("ol" if re.match(r"^\s*\d", line) else "ul", item.group(1))
        elif line[:1] in " \t" and blocks.items:  # a wrapped list item
            blocks.items[-1] += " " + stripped
        else:
            if blocks.items:
                blocks.flush()
            blocks.para.append(stripped)
    blocks.close_entry()
    header = []
    if name:
        header.append(f"<h1>{_inline(name)}</h1>")
    if tagline:
        header.append(f'<p class="tagline">{_inline(tagline)}</p>')
    contact = _contact(preamble)
    if contact:
        header.append(contact)
    head = f'<header class="cv-header"><<photo>>{chr(10).join(header)}</header>' if header else ""
    return "\n".join(x for x in [head, *blocks.out] if x)


def letter_header(cv_md: str) -> tuple[str, str]:
    """The letter's header from the CV: ``(html, name)``, the CV's name and contact details in the `letter-header`
    shape (what the tailor writes at the top of a letter); ``("", "")`` for a CV with no name. The tagline is left out."""
    name, _, preamble = _header_parts(cv_md)
    if not name:
        return "", ""
    return f'<header class="letter-header"><h1>{_inline(name)}</h1>{_contact(preamble)}</header>', name
