"""Deterministic pre-match ranking pass for job postings (issue #143).

Runs after ``condense`` (end of ``scrape``), before any LLM call. Ranks
surviving postings offline so only the plausible ones are sent to the
matcher, cutting LLM cost roughly linearly with the cut.

Public API
----------
``prescreen_score(posting, profile_terms, config) -> float``
    Weighted sum in [0, 1] of title similarity, skill overlap (against
    ``description_condensed``), seniority match, and location compatibility.

``prescreen(paths, config, profile_terms) -> list[Path]``
    Scores every surviving posting, writes ``prescreen_score`` back to each
    JSON, and returns every on-topic posting (its title or ``title_en`` on the
    profile's topic terms) that clears ``prescreen_min`` (config, default 0.15),
    plus the best off-topic ones, which ``prescreen_top_n`` (config, default 40,
    counting the on-topic ones) caps. Postings cut here
    get ``score=0.0``, ``score_reason="prescreen: <score> below cutoff"`` so
    they stay on disk (counted as filtered out by `status`) but are never re-sent to the LLM.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from door import i18n
from door.matching import title_fit
from door.matching.prefilter import _is_location_compatible

_DEFAULT_TOP_N = 40
_DEFAULT_MIN = 0.15

_TITLE_WEIGHT = 0.5
_SKILL_WEIGHT = 0.3
_SENIORITY_WEIGHT = 0.1
_LOCATION_WEIGHT = 0.1



@lru_cache(maxsize=None)
def _seniority(codes: tuple[str, ...] | None) -> tuple[dict[str, str], re.Pattern]:
    """Seniority words of the languages ``codes`` (``None``: every language;
    see ``i18n.scope``), each mapped to its canonical level, so "Ledende" and
    "Lead" are the same level and a Danish compound ("Seniorudvikler") still
    counts as "senior"; and a pattern finding them."""
    levels = i18n.seniority_words(codes)
    return levels, i18n.compile_words(list(levels))

_WORD_RE = re.compile(r"[^\W_]+")  # Unicode letters and digits (#514)


def _tokenize(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text or "")}


def _title_similarity(title: str, role_targets: list[str]) -> float:
    """Max similarity of ``title`` against any of ``role_targets``.

    Combines token Jaccard overlap with a difflib.SequenceMatcher ratio so
    both "same words, different order" and "close spelling" score highly.
    """
    if not title or not role_targets:
        return 0.0

    title_tokens = _tokenize(title)
    title_lower = title.lower()

    best = 0.0
    for target in role_targets:
        target_tokens = _tokenize(target)
        if title_tokens and target_tokens:
            union = title_tokens | target_tokens
            jaccard = len(title_tokens & target_tokens) / len(union) if union else 0.0
        else:
            jaccard = 0.0
        ratio = SequenceMatcher(None, title_lower, target.lower()).ratio()
        score = max(jaccard, ratio)
        best = max(best, score)
    return best


def _skill_overlap(description_condensed: str, profile_terms: set[str]) -> float:
    if not profile_terms:
        return 0.0
    text_lower = (description_condensed or "").lower()
    present = sum(1 for term in profile_terms if term and term in text_lower)
    return present / len(profile_terms)


def _level_of(word: str, levels: dict[str, str]) -> str | None:
    word = word.lower()
    if word in levels:
        return levels[word]
    for entry, level in levels.items():  # a "senior*" prefix entry
        if entry.endswith("*") and word.startswith(entry[:-1]):
            return level
    return None


def _seniority_terms(texts: list[str], language: str | None = None) -> set[str]:
    """The canonical seniority levels named in ``texts``, read with the words of
    ``language`` and English (every language when it is ``None``)."""
    levels, pattern = _seniority(i18n.scope(language))
    found: set[str] = set()
    for text in texts:
        for m in pattern.findall(text or ""):
            level = _level_of(m, levels)
            if level:
                found.add(level)
    return found


def _seniority_match(title: str, role_targets: list[str], language: str | None = None) -> float:
    """``title`` is read in the ad's ``language``; the targets, the candidate's
    own words, in every language."""
    title_terms = _seniority_terms([title], language)
    target_terms = _seniority_terms(role_targets)
    if not title_terms and not target_terms:
        # Neither mentions seniority — neutral, small credit.
        return 0.5
    if not target_terms:
        return 0.5
    if title_terms & target_terms:
        return 1.0
    if title_terms:
        # Mismatched seniority (e.g. "junior" title vs "senior" target).
        return 0.0
    return 0.5


def prescreen_score(posting: dict, profile_terms: set[str], config: dict) -> float:
    """Return a deterministic, offline plausibility score in [0, 1].

    Weighted sum of title similarity (0.5), skill overlap against
    ``description_condensed`` (0.3), seniority match (0.1), and location
    compatibility (0.1). The title parts take the better of ``title`` and its
    English translation ``title_en`` (set by ``door.matching.language``), so a
    translation helps an English profile and never hurts a Danish one.
    """
    role_targets: list[str] = config.get("role_targets", []) or []
    # (title, the language it is written in): the English translation is English.
    titles = [(posting.get("title", ""), posting.get("language"))]
    if posting.get("title_en"):
        titles.append((posting["title_en"], "en"))

    title_score = max(_title_similarity(t, role_targets) for t, _ in titles)
    skill_score = _skill_overlap(posting.get("description_condensed", ""), profile_terms)
    seniority_score = max(_seniority_match(t, role_targets, lang) for t, lang in titles)

    location_score = (
        1.0
        if _is_location_compatible(posting.get("location", ""), config)
        else 0.0
    )

    total = (
        _TITLE_WEIGHT * title_score
        + _SKILL_WEIGHT * skill_score
        + _SENIORITY_WEIGHT * seniority_score
        + _LOCATION_WEIGHT * location_score
    )
    return max(0.0, min(1.0, total))


def prescreen(paths: list[Path], config: dict, profile_terms: set[str]) -> list[Path]:
    """Rank surviving postings offline; return the ones worth sending to the LLM.

    Writes ``prescreen_score`` into every posting JSON. On-topic postings
    (``title_fit.on_topic`` on ``title`` or ``title_en``) at or above
    ``prescreen_min`` (config, default 0.15) are all kept; ``prescreen_top_n``
    (config, default 40) caps only the off-topic ones, with
    ``max(0, top_n - kept on-topic)`` slots. The others are marked with ``score=0.0`` and
    ``score_reason="prescreen: <score> below cutoff"`` and excluded from the
    returned list; they stay on disk (counted as filtered out by `status`) for a
    future forced re-score.
    """
    if not paths:
        return []

    top_n = config.get("prescreen_top_n", _DEFAULT_TOP_N)
    min_score = config.get("prescreen_min", _DEFAULT_MIN)

    terms = title_fit.topic_terms(config)
    scored: list[tuple[Path, dict, float, bool]] = []
    for p in paths:
        path = Path(p)
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("score") is not None:
            continue  # already scored or cut: never overwrite (second same-day scrape)
        score = prescreen_score(data, profile_terms, config)
        on = any(
            title_fit.on_topic(t, terms)
            for t in (data.get("title"), data.get("title_en"))
            if t
        )
        scored.append((path, data, score, on))

    # Highest score first; stable for equal scores (preserves input order).
    ranked = sorted(scored, key=lambda item: item[2], reverse=True)

    keep_paths = {path for path, _d, score, on in ranked if on and score >= min_score}
    slots = max(0, top_n - len(keep_paths))
    for path, _d, score, on in ranked:
        if slots <= 0:
            break
        if not on and score >= min_score:
            keep_paths.add(path)
            slots -= 1

    surviving: list[Path] = []
    for path, data, score, _on in scored:
        data["prescreen_score"] = score
        if path in keep_paths:
            surviving.append(path)
        else:
            data["score"] = 0.0
            data["score_reason"] = f"prescreen: {score:.2f} below cutoff"
        try:
            path.write_text(json.dumps(data, indent=2, default=str))
        except OSError:
            pass

    # Preserve original input ordering among survivors.
    surviving_set = set(surviving)
    return [Path(p) for p in paths if Path(p) in surviving_set]
