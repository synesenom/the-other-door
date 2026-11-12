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
            findings.append({"kind": "link_mismatch", "excerpt": _excerpt(f"{link.get_text(' ')} -> {target}")})
    lines = (" ".join(line.split()) for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line), findings


def _text_pass(text: str) -> tuple[str, list[dict]]:
    findings: list[dict] = []
    bidi = _BIDI.findall(text)
    if bidi:
        findings.append({"kind": "invisible_unicode", "excerpt": f"{len(bidi)} hidden direction/tag characters"})
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
