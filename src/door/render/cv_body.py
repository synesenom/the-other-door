"""`cv.md` as a body in the tailor's vocabulary, with no model (#431): the CV as it is, in the building blocks `compile` prints
(the CV-style sample of #465 and `scripts/record_cv_reading.py`'s made-up tailored CVs).

`body(cv_md, reading)`: the same shapes the
tailor agent writes (`html_guard`'s tags and classes; `src/door/prompts/tailor.md`'s building blocks), made from the
markdown that `draft_cv` and `init` write. What the CV means comes from `reading`, the one reading of it
(`core/cv_read.read`, a dict): no word list of any language is here. Nothing is translated, tailored or dropped; text and
links are escaped and only `https:`, `mailto:` and `#` links are kept.

- `# Name` is the header's `<h1>`, a `> line` its tagline, the reading's `contacts` its contact details, one `<span>` each with its kind as a class, in the
  template's order (phone, email, web, linkedin, github, location), nothing else of the header's lines; the `<<photo>>`
  token comes first in the header, as the tailor writes it (`compile` swaps it);
- `## Heading` is an `<h2 class="kind-<kind>">`, the kind and the text of the reading's section at the same place.
- `### Heading` is an `<div class="entry">` whose `<h3>` has the reading's `role`, `org`, `dates` and `place` in spans
  with `sep` spans between (` | `, ` - `, ` | `); an entry the reading has no parts for is a role alone. Its bullets and
  paragraphs go inside it.
- `- item` is an `<li>` of a `<ul>`, `1. item` of an `<ol>`; other lines are a `<p>` (consecutive lines joined).
- An item the reading's `levels` lists with a level, `**Danish** — conversational`, gets `<span class="level level-N">`
  around the level word as written; an item it does not list, or lists with no level, gets none: a level is never guessed.
- No `<!-- Keywords -->` or `<!-- Tailoring -->` notes: this body is not tailored.
"""

from __future__ import annotations

import html
import re

from door.core import cv_read
from door.render import html_guard

_SAFE_URL = re.compile(r"(?:https://|mailto:|#)[^\s<>\"']+$", re.I)
_INLINE = re.compile(r"\*\*(?P<b>.+?)\*\*|\*(?P<i>[^*\s][^*]*?)\*|\[(?P<t>[^\]]+)\]\((?P<u>(?:[^()\s]|\([^()\s]*\))+)\)")
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


def _detail(kind: str, value: str) -> str:
    cls = f' class="{kind}"'
    plain = re.sub(r"\*\*|\[|\]\(.*?\)", "", value)  # a markdown link or bold in a detail: its text
    mail = re.fullmatch(r"(?:mailto:)?([^\s@<>\"']+@[^\s@<>\"']+)", plain)
    if mail and kind == "email":
        address = html.escape(mail.group(1))
        return f'<span class="email"><a href="mailto:{address}">{address}</a></span>'
    if kind in ("web", "linkedin", "github"):
        href = _link(plain)
        if href:
            text = re.sub(r"^https://(?:www\.)?|/$", "", href) if kind == "web" else re.sub(r"^https://", "", href).rstrip("/")
            return f'<span{cls}><a href="{html.escape(href)}">{html.escape(text, quote=False)}</a></span>'
    return f"<span{cls}>{_inline(value)}</span>"


def _contact(reading: dict) -> str:
    """The contact paragraph: the reading's contacts, in the template's order. Nothing else of the header's lines is
    a contact detail: what the reading did not find is not written."""
    contacts = reading["contacts"]
    spans = [_detail(kind, c["value"]) for kind in cv_read.CONTACT_KINDS for c in contacts if c["kind"] == kind]
    return f'<p class="contact">{"".join(spans)}</p>' if spans else ""


def _entry_heading(text: str, reading: dict) -> str:
    """An entry's `<h3>`: the reading's parts of the `###` line `text` in spans, a role alone for a line it has none of."""
    span = lambda cls, v: f'<span class="{cls}">{_inline(v)}</span>'  # noqa: E731
    entry = next((e for e in reading["entries"] if cv_read.squash(e["heading"]) == cv_read.squash(text)), {})
    pieces = [(cls, entry[cls], sep) for cls, sep in (("role", ""), ("org", " | "), ("dates", " - "), ("place", " | "))
              if entry.get(cls)]
    if not any(cls in ("role", "org") for cls, _, _ in pieces):
        pieces = [("role", text, "")]
    out: list[str] = []
    for i, (cls, value, sep) in enumerate(pieces):
        if i:
            out.append(f'<span class="sep">{sep}</span>')
        out.append(span(cls, value))
    return f"<h3>{''.join(out)}</h3>"


def _level_item(text: str, levels: dict[str, int]) -> str | None:
    """The list item `text` as a level item when the reading lists its name with a level: the name, then the level word
    as written after a separator (`**Danish** — conversational`, `Danish (B2)`), whatever the language."""
    plain = text.replace("**", "").strip()
    for item in sorted(levels, key=len, reverse=True):
        rest = plain[len(item):]
        if plain.startswith(item) and re.match(r"[\s—–:(-]", rest):
            word = re.sub(r"[\s)]+$", "", re.sub(r"^[\s—–:(-]+", "", rest))
            if word:
                return (f'<li><strong>{_inline(item)}</strong> <span class="level level-{levels[item]}">'
                        f'{html.escape(word, quote=False)}</span></li>')
    return None


class _Blocks:
    """The body's blocks as `body` reads the lines: a paragraph or list is kept as text until it ends, and is built
    then, so a wrapped list item is whole before it is read for a level."""

    def __init__(self, levels: dict[str, int]) -> None:
        self.out: list[str] = []
        self.entry = False
        self.levels = levels
        self.para: list[str] = []
        self.tag = ""  # the open list's tag
        self.items: list[str] = []

    def flush(self) -> None:
        if self.para:
            self.out.append(f"<p>{_inline(' '.join(self.para))}</p>")
            self.para = []
        if self.items:
            built = [_level_item(t, self.levels) or f"<li>{_inline(t)}</li>" for t in self.items]
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


def _header_parts(cv_md: str) -> tuple[str | None, str | None]:
    """What is above the first `## ` heading: the name (`# `) and the tagline (the first `>` line)."""
    name = tagline = None
    for raw in cv_md.splitlines():
        stripped = raw.strip()
        if raw.startswith("## "):
            break
        if stripped.startswith("# ") and name is None:
            name = stripped[2:].strip()
        elif stripped.startswith(">"):
            tagline = tagline or stripped.lstrip("> ").strip() or None
    return name, tagline


def body(cv_md: str, reading: dict) -> str:
    """The CV in `cv_md` as a body (see the module's docstring); '' for a CV with nothing in it. `reading` is
    `cv_read.read(cv_md)`: its sections, entries, contacts and levels give the body its classes."""
    name, tagline = _header_parts(cv_md)
    blocks = _Blocks({lv["item"]: lv["level"] for lv in reading["levels"] if lv["level"] is not None})
    sections = iter(reading["sections"])
    in_header = True
    for raw in cv_md.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if line.startswith("## "):  # the test `cv_read` counts the sections by
            in_header = False
            blocks.close_entry()
            section = next(sections)
            blocks.out.append(f'<h2 class="{html_guard.KIND_PREFIX}{section["kind"]}">{_inline(section["heading"])}</h2>')
        elif in_header:
            continue
        elif line.startswith("### "):
            blocks.close_entry()
            blocks.out.append(f'<div class="entry">{_entry_heading(stripped[4:].strip(), reading)}')
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
    contact = _contact(reading)
    if contact:
        header.append(contact)
    head = f'<header class="cv-header"><<photo>>{chr(10).join(header)}</header>' if header else ""
    return "\n".join(x for x in [head, *blocks.out] if x)
