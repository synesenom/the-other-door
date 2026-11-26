"""Posting integrity gate (#368): clean an ad before a model reads it.

Pure and offline. `check` removes what a candidate cannot see (CSS-hidden and aria-hidden
elements, bidi controls) and the lines addressed to a model rather than a candidate
(phrases in `i18n/lang/*.toml`'s ``[injection]``), and reports each removal as a finding.
`apply` and `ensure` store the verdict on a posting dict; they never raise, so a failure
here never drops a posting or stops a run. A finding's excerpt is for the user's `show`,
never for a prompt.
"""

import re
from urllib.parse import urlparse

from door import i18n

_EXCERPT = 80
# Bidi embeddings, overrides and isolates, and the invisible "tag" block: a person reading
# the ad sees nothing, a model reads them. Flagged.
_BIDI = re.compile("[‪-‮⁦-⁩\U000e0000-\U000e007f]")
# Zero-width spaces/joiners, direction marks, word joiner, BOM: stripped without a finding.
_ZERO_WIDTH = re.compile("[​-‏⁠﻿]")
_URL_TEXT = re.compile(r"(?i)\b(?:https?://|www\.)([a-z0-9.-]+)")
_ZERO = re.compile(r"^0(?:\.0*)?(?:[a-z%]*)$")


def _excerpt(text: str) -> str:
    return " ".join(text.split())[:_EXCERPT]


def _style(tag) -> dict[str, str]:
    props = {}
    for part in str(tag.get("style") or "").split(";"):
        name, _, value = part.partition(":")
        if value.strip():
            props[name.strip().lower()] = re.sub(r"\s*!important", "", value.strip().lower()).strip()
    return props


def _hidden_kind(tag) -> str | None:
    if tag.has_attr("hidden"):
        return "hidden_css"
    if str(tag.get("aria-hidden") or "").lower() == "true":
        return "aria_hidden"
    style = _style(tag)
    if style.get("display") == "none" or style.get("visibility") == "hidden":
        return "hidden_css"
    if _ZERO.match(style.get("font-size", "x")) or _ZERO.match(style.get("opacity", "x")):
        return "hidden_css"
    background = style.get("background-color") or style.get("background")
    if background and style.get("color") == background:
        return "hidden_css"
    return None


def _host(url: str) -> str:
    host = (urlparse(url if "//" in url else f"//{url}").hostname or "").lower()
    return host.removeprefix("www.")


def _html_pass(html: str) -> tuple[str, list[dict]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    findings: list[dict] = []
    for tag in soup.find_all(True):
        if getattr(tag, "decomposed", False):
            continue
        kind = _hidden_kind(tag)
        if kind:
            text = tag.get_text(" ")
            if text.strip():
                findings.append({"kind": kind, "excerpt": _excerpt(text)})
            tag.decompose()
    for link in soup.find_all("a", href=True):
        shown = _URL_TEXT.search(link.get_text(" "))
        target = _host(str(link["href"])) if str(link["href"]).lower().startswith(("http://", "https://", "//")) else ""
        if shown and target and _host(shown.group(0)) != target:
            findings.append({"kind": "link_mismatch", "excerpt": _excerpt(f"{link.get_text(' ')} opens {target}")})
    lines = (" ".join(line.split()) for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line), findings


def _text_pass(text: str) -> tuple[str, list[dict]]:
    findings: list[dict] = []
    bidi = _BIDI.findall(text)
    if bidi:
        findings.append({"kind": "invisible_unicode", "excerpt": f"{len(bidi)} hidden characters"})
    text = _ZERO_WIDTH.sub("", _BIDI.sub("", text))
    phrases = i18n.injection_phrases()
    kept = []
    for line in text.split("\n"):
        low = " ".join(line.lower().split())
        kind = next(
            (k for k in ("score_request", "instruction") if any(p in low for p in phrases[k])),
            None,
        )
        if kind:
            findings.append({"kind": kind, "excerpt": _excerpt(line)})
        else:
            kept.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip(), findings


def check(text: str, html: str | None = None) -> dict:
    """``{"clean_text", "verdict": "clean" | "suspicious", "findings": [{"kind", "excerpt"}]}``.

    With ``html`` the text is read from it (``text`` is ignored) after dropping hidden
    elements; without, only the text rules apply. Kinds: ``hidden_css``, ``aria_hidden``,
    ``invisible_unicode``, ``instruction``, ``score_request``, ``link_mismatch``.
    """
    findings: list[dict] = []
    if html is not None:
        text, findings = _html_pass(html)
    text, more = _text_pass(text or "")
    findings += more
    return {"clean_text": text, "verdict": "suspicious" if findings else "clean", "findings": findings}


_MIN_QUOTE_WORDS, _MIN_QUOTE_CHARS = 3, 15


def _quote_pattern(quote: str):
    """The quote's words in order with any run of spaces, punctuation or bullets between them (so a quote read
    from the condensed text is found in the full one), case-insensitive; None for a quote too short to be told
    from ordinary text."""
    words = re.findall(r"\w+", quote)
    if len(words) < _MIN_QUOTE_WORDS or len(quote.strip()) < _MIN_QUOTE_CHARS:
        return None
    trail = re.search(r"[^\w\s]*$", quote.strip()).group()  # the quote's own closing punctuation goes with it
    return re.compile(r"\W+".join(re.escape(w) for w in words) + (re.escape(trail) if trail else "") + r"[ \t]*", re.IGNORECASE)


def find_quote(text: str, quote: str) -> bool:
    """True when ``quote`` (long enough to act on) is in ``text``."""
    pattern = _quote_pattern(quote)
    return bool(pattern and pattern.search(text))


def _cut(text: str, pattern) -> str:
    def gone(m):  # the span alone; its trailing blanks go with it, keeping one between two words it parted
        before = text[m.start() - 1] if m.start() else " "
        after = text[m.end()] if m.end() < len(text) else " "
        return " " if before.isalnum() and after.isalnum() else ""

    return re.sub(r"[ \t]+\n", "\n", pattern.sub(gone, text)).strip()


def remove_quoted(posting: dict, quotes: list[str]) -> tuple[dict, list[str]]:
    """``(copy, removed)``: ``posting`` with exactly each quoted span taken out of its title, company and
    description, an ``instruction`` finding per quote found there, the verdict suspicious and the stale
    ``description_condensed`` dropped. ``removed`` is the quotes found; a posting is unchanged when it is empty.
    The quotes are checked by the caller."""
    patterns = [(q, _quote_pattern(q)) for q in quotes]
    out, removed = dict(posting), []
    for quote, pattern in patterns:
        if pattern is None:
            continue
        for field in ("title", "company", "description"):
            text = str(out.get(field) or "")
            if pattern.search(text):
                out[field] = _cut(text, pattern)
                if quote not in removed:
                    removed.append(quote)
    if not removed:
        return posting, []
    out.pop("description_condensed", None)
    out["description"] = re.sub(r"\n{3,}", "\n\n", str(out.get("description") or "")).strip()
    block = posting.get("integrity") or {}
    out["integrity"] = {
        "verdict": "suspicious",
        "findings": [*(block.get("findings") or []), *({"kind": "instruction", "excerpt": _excerpt(q)} for q in removed)],
    }
    return out, removed


def stored(result: dict) -> dict:
    """The part of a `check` result a posting keeps: ``{"verdict", "findings"}``."""
    return {"verdict": result["verdict"], "findings": result["findings"]}


def apply(posting: dict) -> bool:
    """Gate ``posting["description"]`` in place: clean text, ``integrity`` set, a stale
    ``description_condensed`` dropped when the text changed. False (posting untouched) on a failure."""
    try:
        original = str(posting.get("description") or "")
        result = check(original)
    except Exception:  # the gate must never stop a run or drop an ad
        return False
    if result["clean_text"] != original.strip():
        posting.pop("description_condensed", None)
        posting["description"] = result["clean_text"]
    posting["integrity"] = stored(result)
    return True


def ensure(posting: dict) -> bool:
    """`apply` to a posting stored before the gate existed; a no-op (False) when it has a verdict."""
    if posting.get("integrity"):
        return False
    return apply(posting)


def for_model(posting: dict) -> dict:
    """A copy of ``posting`` safe to hand a model: the ``integrity`` findings keep their
    ``kind`` but lose the ``excerpt`` of the removed text (only `show` displays that)."""
    safe = dict(posting)
    block = posting.get("integrity")
    if isinstance(block, dict):
        safe["integrity"] = {
            **block,
            "findings": [{k: v for k, v in f.items() if k != "excerpt"} for f in block.get("findings") or []],
        }
    return safe
