"""Deterministic pre-match condensing pass for job postings (issue #143).

Shrinks each posting's ``description`` to the parts that matter for scoring
(role summary, responsibilities, requirements, location/remote/salary lines,
language requirements) before it is ever sent to an LLM. Pure Python, no
network, no randomness — same input always produces the same output.

Public API
----------
``split_sections(text)``
    Split raw description text into ``(heading, body)`` sections using a
    heading-detection heuristic (colon-terminated lines, ALL CAPS lines,
    Title Case lines, or a line matching a known heading in any language of
    ``src/door/i18n/lang/``, including a short question such as "Hvem er du?").

``condense_description(text, *, keep_terms, max_chars=3000)``
    Drop boilerplate sections (about-us, benefits, EEO, how-to-apply, ...)
    wholesale, then keep sentences/lines that contain a requirement marker,
    a term from ``keep_terms``, or an always-keep pattern (language
    requirement, remote/hybrid/on-site, salary, seniority). Always keeps
    the first two sentences (role summary) and truncates to ``max_chars``,
    preferring requirement content over responsibilities when cutting.

``extract_skill_terms(cv_md, config)``
    Tokens from the CV's Skills section plus ``role_targets``/
    ``search_keywords``, lower-cased, deduplicated, >= 3 chars.

``condense_postings(paths, profile_terms, config)``
    Batch driver: reads each posting JSON, writes back
    ``description_condensed``, and returns ``{"count", "avg_ratio"}``
    stats for the scrape summary. Mirrors the ``prefilter``/``dedup``
    on-disk mutation convention.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from door import i18n

# ---------------------------------------------------------------------------
# Vocabularies, per set of languages (i18n.scope: the ad's language plus
# English; every language when it is unknown)
# ---------------------------------------------------------------------------

# A line ending in "?" is a heading only when it is this short and starts with
# a known heading ("Hvem er du?"), never a question in the body text.
_QUESTION_HEADING_MAX_CHARS = 40


@dataclass(frozen=True)
class _Vocab:
    requirement_headings: list[str]
    drop_headings: list[str]
    known_headings: list[str]
    requirement_marker: re.Pattern
    language: re.Pattern
    work_mode: re.Pattern
    salary: re.Pattern
    seniority: re.Pattern
    work_permit: re.Pattern


@lru_cache(maxsize=None)
def _vocab(codes: tuple[str, ...] | None) -> _Vocab:
    """The heading words and always-keep patterns of the languages ``codes``.
    Language names and currency words apply to every ad: an English ad can
    ask for Danish, and a salary in kroner."""
    requirement = i18n.heading_words("requirement", codes)
    responsibility = i18n.heading_words("responsibility", codes)
    drop = i18n.heading_words("drop", codes)
    return _Vocab(
        requirement_headings=requirement,
        drop_headings=drop,
        known_headings=[w.lower() for w in requirement + responsibility + drop],
        requirement_marker=i18n.compile_words(i18n.marker_words("requirement", codes)),
        language=i18n.compile_words(i18n.language_names()),
        work_mode=i18n.compile_words(i18n.marker_words("remote", codes) + i18n.marker_words("onsite", codes)),
        salary=i18n.compile_words(i18n.marker_words("salary", codes) + i18n.currency_words()),
        seniority=i18n.compile_words(list(i18n.seniority_words(codes))),
        # Visa and permit phrases of every language: Danish ads quote the English ones.
        work_permit=i18n.compile_words(i18n.work_permit_words()),
    )


_TRUNCATION_MARKER = " […]"


def _is_heading_line(stripped: str, vocab: _Vocab) -> bool:
    """Return True if a stripped line looks like a section heading."""
    if not stripped or len(stripped) > 80:
        return False

    lower = stripped.lower().rstrip(":").strip()
    if stripped.endswith("?"):
        return len(stripped) <= _QUESTION_HEADING_MAX_CHARS and any(
            lower.startswith(word) for word in vocab.known_headings
        )
    if stripped.endswith((".", "!")):
        return False

    if any(word in lower for word in vocab.known_headings):
        return True

    if stripped.endswith(":"):
        return True

    letters = [c for c in stripped if c.isalpha()]
    if len(letters) >= 3 and all(c.isupper() for c in letters):
        return True

    words = stripped.split()
    if words and len(words) <= 8:
        if all(w[:1].isupper() for w in words if w[:1].isalpha()):
            # Require at least one alphabetic-leading word to avoid matching
            # lines that are purely punctuation/numbers.
            if any(w[:1].isalpha() for w in words):
                return True

    return False


def split_sections(text: str, language: str | None = None) -> list[tuple[str, str]]:
    """Split ``text`` into ``(heading, body)`` sections, recognising the
    headings of ``language`` (an ISO 639-1 code) and English, or of every
    language when it is ``None``.

    The text before the first detected heading is returned with heading
    ``""``. Sections with neither heading nor body are dropped.
    """
    vocab = _vocab(i18n.scope(language))
    if not text:
        return []

    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines():
        stripped = line.strip()
        if _is_heading_line(stripped, vocab):
            heading = stripped.rstrip(":?").strip()
            sections.append((heading, []))
        else:
            sections[-1][1].append(line)

    result = []
    for heading, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if heading or body:
            result.append((heading, body))
    return result


def _is_drop_heading(heading: str, vocab: _Vocab) -> bool:
    lower = heading.lower()
    return any(word in lower for word in vocab.drop_headings)


def _is_requirement_heading(heading: str, vocab: _Vocab) -> bool:
    lower = heading.lower()
    return any(word in lower for word in vocab.requirement_headings)


def _split_units(text: str) -> list[str]:
    """Split text into atomic keep/drop units (roughly one per line/sentence)."""
    units: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("•*-").strip()
        if not line:
            continue
        if len(line) > 200:
            parts = re.split(r"(?<=[.!?])\s+", line)
            units.extend(p.strip() for p in parts if p.strip())
        else:
            units.append(line)
    return units


def _should_keep_unit(unit: str, keep_terms_lower: set[str], vocab: _Vocab) -> bool:
    for pattern in (vocab.requirement_marker, vocab.language, vocab.work_mode, vocab.salary, vocab.seniority, vocab.work_permit):
        if pattern.search(unit):
            return True
    unit_lower = unit.lower()
    return any(term in unit_lower for term in keep_terms_lower)


def condense_description(
    text: str, *, keep_terms: set[str] = frozenset(), max_chars: int = 3000, language: str | None = None
) -> str:
    """Condense a posting description to the parts that matter for scoring.

    ``language`` is the ad's ISO 639-1 code (the posting's ``language``): only
    its words and English ones count as headings and markers; ``None`` uses
    every language. Deterministic and pure: the same arguments always produce
    the same output. No network, no LLM.
    """
    if not text:
        return text
    vocab = _vocab(i18n.scope(language))

    keep_terms_lower = {t.lower() for t in keep_terms if t}

    all_units = _split_units(text)
    summary_units = all_units[:2]
    summary_seen = set(summary_units)

    requirement_blocks: list[str] = []
    other_blocks: list[str] = []
    # A visa or work-permit line can decide the score on its own (``needs_work_permit``),
    # so it is lifted out of whatever section holds it and never truncated away.
    permit_units: list[str] = []

    for heading, body in split_sections(text, language):
        units = [u for u in _split_units(body) if u not in summary_seen]
        for unit in units:
            if vocab.work_permit.search(unit) and unit not in permit_units:
                permit_units.append(unit)
        units = [u for u in units if u not in permit_units]
        kept_units = [u for u in units if _should_keep_unit(u, keep_terms_lower, vocab)]
        if not kept_units:
            continue

        if _is_drop_heading(heading, vocab):
            # Drop-sections (about-us, benefits, EEO, how-to-apply, ...) are
            # dropped wholesale *except* for any line that independently
            # matches an always-keep pattern (language requirement, salary,
            # remote/hybrid, a hard requirement marker) — postings sometimes
            # fold a hard requirement into an otherwise boilerplate section.
            # The heading itself is not kept, and the block sinks to the
            # lowest truncation priority.
            other_blocks.append("\n".join(kept_units))
            continue

        block = "\n".join(kept_units)
        if heading:
            block = f"{heading}\n{block}"

        if _is_requirement_heading(heading, vocab):
            requirement_blocks.append(block)
        else:
            other_blocks.append(block)

    summary_block = "\n".join(summary_units)
    permit_block = "\n".join(permit_units)
    priority_blocks = [b for b in (summary_block, permit_block) if b] + requirement_blocks

    result = "\n\n".join(b for b in (priority_blocks + other_blocks) if b)
    if len(result) <= max_chars:
        return result

    # Over budget: drop lower-priority (responsibilities/other) content first.
    result = "\n\n".join(b for b in priority_blocks if b)
    if len(result) <= max_chars:
        budget = max_chars - len(result) - 2  # 2 for the joining "\n\n"
        extra = "\n\n".join(b for b in other_blocks if b)
        if budget > len(_TRUNCATION_MARKER) and extra:
            if len(extra) > budget:
                extra = extra[: budget - len(_TRUNCATION_MARKER)].rstrip() + _TRUNCATION_MARKER
            result = f"{result}\n\n{extra}" if result else extra
        return result[:max_chars]

    # Still over budget even with only priority content — hard truncate.
    return result[: max_chars - len(_TRUNCATION_MARKER)].rstrip() + _TRUNCATION_MARKER


def _extract_skills_section(cv_md: str) -> str:
    """Return the raw text of the CV's skills sections, under any name in any language (empty if none)."""
    if not cv_md:
        return ""
    titles = i18n.cv_section("skills")
    capturing = False
    collected: list[str] = []
    for line in cv_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            capturing = stripped[3:].strip(" *:_").casefold() in titles
            continue
        if capturing:
            collected.append(line)
    return "\n".join(collected)


def extract_skill_terms(cv_md: str, config: dict) -> set[str]:
    """Return a lower-cased, deduplicated set of skill/role tokens (>= 3 chars).

    Pulled from the CV's skills sections (``i18n.cv_section``) plus ``role_targets`` and
    ``search_keywords`` (whole phrases and individual words).
    """
    terms: set[str] = set()

    skills_text = _extract_skills_section(cv_md)
    for token in re.split(r"[,\n;/()]+", skills_text):
        token = token.strip().lower()
        if len(token) >= 3:
            terms.add(token)

    for key in ("role_targets", "search_keywords"):
        for phrase in config.get(key) or []:
            phrase = phrase.strip()
            if not phrase:
                continue
            phrase_lower = phrase.lower()
            if len(phrase_lower) >= 3:
                terms.add(phrase_lower)
            for word in phrase_lower.split():
                word = word.strip(".,")
                if len(word) >= 3:
                    terms.add(word)

    return terms


def condense_postings(
    paths: list[Path], profile_terms: set[str], config: dict
) -> dict:
    """Condense the ``description`` of each posting on disk in place.

    Writes ``description_condensed`` back to each posting JSON. Returns
    ``{"count": n, "avg_ratio": float | None}`` where ``avg_ratio`` is the
    mean ``len(condensed) / len(description)`` across non-empty descriptions
    (``None`` when there is nothing to condense).
    """
    max_chars = config.get("condense_max_chars", 3000)
    count = 0
    ratios: list[float] = []

    for p in paths:
        path = Path(p)
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        description = data.get("description", "") or ""
        condensed = condense_description(
            description, keep_terms=profile_terms, max_chars=max_chars,
            language=data.get("language"),
        )
        data["description_condensed"] = condensed
        try:
            path.write_text(json.dumps(data, indent=2, default=str))
        except OSError:
            continue

        count += 1
        if description:
            ratios.append(len(condensed) / len(description))

    avg_ratio = sum(ratios) / len(ratios) if ratios else None
    return {"count": count, "avg_ratio": avg_ratio}
