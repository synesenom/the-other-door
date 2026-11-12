"""Whether a job title fits the profile's keywords.

Two tests, both pure. `fits` is strict (every word of one keyword): `linkedin` uses it to decide which
cards get a detail request. `on_topic` is the loose one (one of the profile's `topic_terms` or a whole
keyword; without `topic_terms`, any content word of the keywords, synonyms included): the gate for which employers `search` and `discover` queue, and for which followed
employers still yield something (`collect`, `match`). The career-site reader ranks pages with the
same words (`topic_words`).

A topic term is a word or phrase matched whole; ``x*`` starts a word, ``*x`` ends one, ``*x*`` is inside
one. `topic_terms` adds the forms the profile's ad languages need (plurals, a field word ending or inside a
compound) so that `on_topic` stays a plain match. "&" reads as "and", an HTML-escaped one too, and an
all-caps term of three letters or more ("MEAL") is case-sensitive.
"""

from __future__ import annotations

import html
import re
import unicodedata
from functools import lru_cache

from door import i18n

STEM = 5  # letters a word is compared on ("accountant" ~ "accounting")


def keywords(config: dict) -> list[str]:
    """The terms a title is compared with: ``search_keywords``, else ``role_targets``."""
    return list(config.get("search_keywords") or config.get("role_targets") or [])


def _stems(text: str) -> set[str]:
    return {w[:STEM] for w in re.findall(r"\w+", text.lower())}


def fits(title: str, terms: list[str]) -> bool:
    """Whether *title* has every word of some term, compared on the first `STEM` letters and in
    any order. Job boards also return loosely related jobs; only the ones that fit count."""
    have = _stems(title or "")
    return any(_stems(k) and _stems(k) <= have for k in terms)


def any_fits(titles, terms: list[str]) -> bool:
    return any(fits(t, terms) for t in titles)


def squash(text: str) -> str:
    """Lower-case ASCII words of a name or URL path, one space between: ``Dalsvej-99/Hørsholm`` -> ``dalsvej 99 hrsholm``. Pure."""
    ascii_ = unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", ascii_))


def name_pattern(names: list[str]) -> re.Pattern | None:
    """A whole-word pattern over *names* (a trailing ``*`` also matches longer words)
    in every spelling a URL slug may give them, for text from `squash`. Pure."""
    parts = set()
    for name in names:
        starred = name.endswith("*")
        for form in i18n.slug_forms(name.rstrip("*")):
            words = squash(form)
            if words:
                parts.add(re.escape(words) + ("" if starred else r"(?![a-z0-9])"))
    if not parts:
        return None
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(sorted(parts, key=len, reverse=True)) + ")")


_CAPS = re.compile(r"[A-Z0-9]{3,}")  # an abbreviation: matched in this case, so "MEAL" is not a "meal"
MIN_INFIX = 6  # letters a term needs to match inside or at the end of a longer word
MIN_PLURAL = 4  # letters a term needs for its plural forms to be tried


def _is_caps(term: str) -> bool:
    return bool(_CAPS.fullmatch(term)) and any(c.isalpha() for c in term)


def _letters(text: str) -> int:
    return sum(c.isalpha() for c in text)


def _topic_text(text: str) -> str:
    """`squash` of *text* with HTML entities unescaped and "&" read as "and": ``M&amp;E`` -> ``m and e``. Pure."""
    return squash(html.unescape(text or "").replace("&", " and "))


def _title_forms(title: str) -> list[str]:
    """The squashed spellings of a title to match terms against: as written and, when a word is
    hyphenated (``El-installatør``), the hyphenated pieces joined (``elinstallatør``). Pure."""
    text = html.unescape(title or "")
    forms = [_topic_text(text)]
    joined = re.sub(r"(?<=[^\W_])-(?=[^\W_])", "", text)
    if joined != text:
        forms.append(_topic_text(joined))
    return forms


def _term_regex(term: str, stops: frozenset[str]) -> str | None:
    """The pattern of one topic term over `_title_forms` text, or ``None`` when it is empty."""
    lead, trail = term.startswith("*"), term.endswith("*")
    core = term.strip("*")
    alternatives = set()
    for form in i18n.slug_forms(html.unescape(core).replace("&", " and ")):
        words = squash(form).split()
        if not words:
            continue
        pattern = re.escape(words[0])
        for i, word in enumerate(words[1:], 1):
            pattern += rf"(?: {re.escape(word)})?" if word in stops and i < len(words) - 1 else " " + re.escape(word)
        alternatives.add(("" if lead else "(?<![a-z0-9])") + pattern + ("" if trail else "(?![a-z0-9])"))
    if not alternatives:
        return None
    return "(?:" + "|".join(sorted(alternatives, key=len, reverse=True)) + ")"


@lru_cache(maxsize=64)
def _compile(terms: tuple[str, ...]) -> tuple[re.Pattern | None, re.Pattern | None, re.Pattern | None]:
    """``(ordinary terms, case-sensitive abbreviations, those abbreviations in lower case)``, each a pattern or ``None``."""
    stops = frozenset(i18n.stop_words())
    ordinary, caps = [], []
    for term in terms:
        if _is_caps(term):
            caps.append(term)
        elif (rx := _term_regex(term, stops)):
            ordinary.append(rx)
    cased = re.compile("(?<![A-Za-z0-9])(?:" + "|".join(map(re.escape, caps)) + ")(?![A-Za-z0-9])") if caps else None
    lowered = [rx for t in caps if (rx := _term_regex(t.lower(), stops))]
    return (
        re.compile("|".join(ordinary)) if ordinary else None,
        cased,
        re.compile("|".join(lowered)) if lowered else None,
    )


def on_topic(title: str, terms: list[str]) -> bool:
    """Whether *title* holds any of *terms* (from `topic_terms`) as a whole word or phrase (``x*``, ``*x``
    and ``*x*`` also as the start, end or inside of a word). Pure."""
    ordinary, cased, lowered = _compile(tuple(terms))
    title = title or ""
    if ordinary and any(ordinary.search(form) for form in _title_forms(title)):
        return True
    if cased and cased.search(html.unescape(title)):
        return True
    return bool(lowered and title.isupper() and any(lowered.search(form) for form in _title_forms(title)))


def topic_words(config: dict) -> list[str]:
    """The content words of the keywords: not stop, seniority or generic role words ("consultant",
    "partner"); "&" abbreviations (``c&b``) and all-caps ones (``MEAL``) whole. A keyword of role nouns
    only is kept as a phrase. Pure."""
    filler = i18n.compile_words([*i18n.stop_words(), *i18n.seniority_words()])
    nouns = i18n.compile_words(i18n.role_nouns())
    # A rank of several words ("assistant professor") goes first, or "assistant" alone would be a topic word.
    ranks = [w for w in i18n.seniority_words() if " " in w or "-" in w]
    rank_phrases = i18n.compile_words(ranks) if ranks else None
    words: set[str] = set()
    for phrase in keywords(config):
        content, roles = [], []
        text = html.unescape(str(phrase))
        if rank_phrases:
            text = rank_phrases.sub(" ", text)
        for token in re.findall(r"[^\W_]+(?:&[^\W_]+)*", text):
            plain = squash(token)
            if "&" in token:
                word = token.lower()
            elif _is_caps(token):
                word = token
            elif len(plain) > 1 and not filler.fullmatch(token.lower()) and not filler.fullmatch(plain):
                word = plain
            else:
                continue
            (roles if nouns.fullmatch(token.lower()) else content).append(word)
        words.update(content or ([" ".join(roles)] if roles else []))
    return sorted(words, key=lambda w: (w.lower(), w))


def _expand(term: str, codes: tuple[str, ...]) -> set[str]:
    """*term* and the forms its ad languages give it, as terms with ``*`` (see the module docstring):
    from six letters a whole word also ends a word (``*physics``) and, in a compounding language, sits
    inside one (``*sygeplejerske*``); the plural endings of the languages; for a phrase in a compounding
    language, a linking ``s`` after its words and a longer last word. Pure."""
    forms = {term}
    if term.startswith("*") or _is_caps(term):
        return forms
    base, prefix = term.rstrip("*"), term.endswith("*")
    words = base.split()
    if not words:
        return forms
    compounding = bool(set(codes) & i18n.compounding_codes())
    suffixes = i18n.plural_suffixes(codes)
    last = words[-1]
    head = " ".join(words[:-1])
    glue = (head + " ") if head else ""
    if len(words) == 1 and _letters(last) >= MIN_INFIX:
        forms.add(f"*{base}*" if compounding else f"*{base}" + ("*" if prefix else ""))
        if compounding:
            return forms
    if prefix:
        return forms
    if _letters(last) >= MIN_PLURAL:
        forms.update(glue + last + suffix for suffix in suffixes)
        if len(words) == 1 and _letters(last) >= MIN_INFIX:
            forms.update(f"*{last}{suffix}" for suffix in suffixes)
    if compounding and len(words) > 1:
        stops = set(i18n.stop_words())
        linked = " ".join(w if w in stops or _letters(w) < 3 else w + "s" for w in words[:-1])
        forms.add(f"{linked} {last}*")
        forms.add(f"{head} {last}*")
    return forms


def topic_terms(config: dict) -> list[str]:
    """The profile's own ``topic_terms`` (proposed with the keywords, in every ad language) and its
    keywords whole, when it has them; else `topic_words` plus, for every synonym group (``ai`` =
    ``artificial intelligence``) one of whose terms the keywords hold whole, the group's other terms.
    Each with the forms the profile's ``languages`` give it (`_expand`). Pure."""
    codes = i18n.language_codes(config.get("languages"))
    own = [str(t) for t in config.get("topic_terms") or [] if str(t).strip()]
    if own:
        terms = {*own, *keywords(config)}
    else:
        words = topic_words(config)
        have = {w.lower() for w in words}
        terms = set(words)
        for group in i18n.synonyms():
            if any(set(squash(term).split()) <= have for term in group if squash(term)):
                terms.update(group)
    return sorted({form for term in terms for form in _expand(term, codes)})
