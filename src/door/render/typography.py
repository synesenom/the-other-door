"""Punctuation spacing at compile time (#146, #143): French sets a narrow no-break space before : ; ! ? and inside
guillemets, which LaTeX's babel did and a browser does not. The tailor writes plain punctuation; `compile` runs this
over the filled body before it is wrapped in the template. The rules are data (`i18n/lang/<xx>.toml` `[typography]`).

Only the text of the page is touched: never a tag, an attribute, a comment, the text of a link (an identifier or an
address: ``arXiv:2408.10754``), a character reference (``&amp;`` holds a semicolon) or a mark inside a word or a
number (``10:30``, ``a?b=c``): a mark takes the space only when whitespace or the end of the text follows it.
"""

from __future__ import annotations

import re

from door import i18n

_MARKUP = re.compile(r"(<!--.*?-->|<[^>]*>)", re.S)
_SPACES = " \t  "


def apply(html: str, language: str | None) -> str:
    """`html` with the language's punctuation spacing set (unchanged for a language with no rules)."""
    pack = i18n.languages().get(language or "")
    rules = pack.typography if pack else None
    if rules is None or not (rules.space_before or rules.guillemets):
        return html
    marks = "".join(re.escape(m) for m in rules.space_before)
    opens = "|".join(re.escape(o) for o, _ in rules.guillemets)
    closes = "|".join(re.escape(c) for _, c in rules.guillemets)
    pattern = re.compile(
        r"(?P<entity>&#?\w+;)"
        + (rf"|(?P<open>{opens})[{_SPACES}]*|[{_SPACES}]*(?P<close>{closes})" if rules.guillemets else "")
        + (rf"|[{_SPACES}]*(?P<mark>[{marks}])(?=\s|$)" if marks else "")
    )

    def sub(match: re.Match) -> str:
        groups = match.groupdict()
        if groups["entity"]:
            return groups["entity"]
        if groups.get("open"):
            return groups["open"] + rules.space
        if groups.get("close"):
            return rules.space + groups["close"]
        return rules.space + groups["mark"]

    parts = _MARKUP.split(html)
    out: list[str] = []
    in_link = False
    for i, part in enumerate(parts):
        if i % 2:  # a tag or a comment
            if re.match(r"<a[\s>]", part, re.I):
                in_link = True
            elif re.match(r"</a\s*>", part, re.I):
                in_link = False
            out.append(part)
            continue
        if in_link or not part:
            out.append(part)
            continue
        following = parts[i + 1] if i + 1 < len(parts) else ""
        # at the end of a text, a mark before a link (``arXiv:`` + ``<a>``) belongs to the link's identifier
        text = part + (" " if not re.match(r"<a[\s>]", following, re.I) else "x")
        text = pattern.sub(sub, _plain_guillemets(text))
        out.append(text[:-1])
    return "".join(out)


_GUILLEMET_ENTITIES = {"&laquo;": "\u00ab", "&raquo;": "\u00bb", "&#171;": "\u00ab", "&#187;": "\u00bb"}


def _plain_guillemets(text: str) -> str:
    """The guillemets written as character references, as the characters (the rules match the characters)."""
    for entity, char in _GUILLEMET_ENTITIES.items():
        text = text.replace(entity, char)
    return text
