"""Cross-site deduplication pass for job postings (issue #44).

Runs after scraping and pre-filtering, before the matcher agent is invoked.

Identity heuristic
------------------
Two postings are considered duplicates when their normalised ``(company, title)``
keys match exactly (a company counts as the first of its *aliases* group: the names
``companies.json`` holds for one followed employer) (configurable via ``dedup_similarity_threshold``; default 1.0
= exact match only), or when they link to the same applicant-tracking project:
an HR-Manager ``ApplicationInit.aspx`` link names it by ``cid`` and ``ProjectId``
whatever channel (``MediaId``) it came through, so Jobindex's copy of an ad and
the ``hr_manager`` feed's own posting meet even when one names the hospital and
the other the region.

Normalisation steps
-------------------
1. Explicit letter substitution BEFORE NFD, from each language's
   ``transliterate`` table in ``src/door/i18n/lang/`` (Danish æ→ae, ø→oe, å→aa;
   NFD alone would drop the combining diacritics rather than substitute).
2. Unicode NFD decomposition + ASCII encoding to strip remaining accents.
3. Lowercase.
4. Strip company-form suffixes (A/S, ApS, I/S, Ltd, GmbH, ...: every
   ``legal_suffixes`` list in ``src/door/i18n/``).
5. Collapse non-alphanumeric runs to a single space; strip.

Canonical selection
-------------------
Within each duplicate group the canonical (kept) posting is chosen by:
1. Highest ``score`` (if any posting in the group has a score).
2. Preferred source (``dedup_source_priority`` config list).
3. The employer's own copy (a per-company feed: Greenhouse, SuccessFactors, a career
   site, ...) over a board's (Jobindex, The Hub, ...): it carries the
   employer's own text and apply link, where a board copy may carry a scraped page.
4. Encounter order (first seen wins).

An *earlier* posting (one written on a previous day, passed by the caller) is only a reference:
it is never dropped or rewritten, and a new posting in its group is its duplicate whatever the
scores. The job was already seen, scored and maybe acted on (an application under its id).

Dropped postings are rewritten in-place with:
  ``score=0.0``, ``score_reason="duplicate"``, ``duplicate_of=<kept_id>``.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from door import i18n
from door.core import ats_detect, sites

# Company-form suffixes to strip from company names (whole words, any case).
_LEGAL_SUFFIX_RE = i18n.compile_words(i18n.legal_suffixes())

# Letter substitution table applied BEFORE NFD normalisation.
_TRANSLITERATION = i18n.transliteration()


def _normalise(company: str, title: str) -> str:
    """Return a normalised string key for (company, title).

    Used to detect cross-site duplicates.  Two postings with the same
    normalised key are considered identical for dedup purposes.
    """
    combined = f"{company} {title}"

    # Step 1: letter substitutions (must happen before NFD)
    combined = combined.translate(_TRANSLITERATION)

    # Step 2: NFD decompose and drop non-ASCII (strips remaining accents)
    combined = unicodedata.normalize("NFD", combined)
    combined = combined.encode("ascii", "ignore").decode("ascii")

    # Step 3: Lowercase
    combined = combined.lower()

    # Step 4: Strip legal suffixes
    combined = _LEGAL_SUFFIX_RE.sub("", combined)

    # Step 5: Collapse non-alphanumeric runs to a single space
    combined = re.sub(r"[^a-z0-9]+", " ", combined).strip()

    return combined


def _project_key(url: str) -> str | None:
    """``hr-manager:<cid>:<project>`` for an HR-Manager application link, else None. Pure."""
    parsed = urlparse(url or "")
    if parsed.netloc.lower() != "candidate.hr-manager.net":
        return None
    query = {k.lower(): v[0] for k, v in parse_qs(parsed.query).items()}
    if not query.get("cid") or not query.get("projectid"):
        return None
    return f"hr-manager:{query['cid']}:{query['projectid']}"


def _pick_canonical(group: list[dict], source_priority: list[str]) -> dict:
    """Return the canonical posting from a duplicate group.

    Selection order:
    1. Highest score (None < 0 < any positive float).
    2. Preferred source (earliest index in source_priority wins).
    3. The employer's own copy over a board's (`_is_employer_copy`).
    4. First in encounter order (index 0 of group).
    """

    def _score(posting: dict) -> float:
        s = posting.get("score")
        return s if s is not None else -1.0

    def _priority(posting: dict) -> int:
        src = posting.get("source", "")
        try:
            return source_priority.index(src)
        except ValueError:
            return len(source_priority)  # not in list → lowest priority

    def _rank(posting: dict) -> tuple:
        return (-_score(posting), _priority(posting), 0 if _is_employer_copy(posting) else 1)

    # min() keeps the first of equals, so encounter order breaks the remaining ties.
    return min(group, key=_rank)


def _is_employer_copy(posting: dict) -> bool:
    """Whether *posting* came from the employer's own feed, not from a board."""
    source = str(posting.get("source") or "")
    return source in sites.FEED_SITES and source not in sites.BOARDS


def _load(paths) -> list[tuple[Path, dict]]:
    """The readable postings with an id among *paths* (a malformed one cannot be canonical)."""
    loaded = []
    for p in paths:
        try:
            data = json.loads(Path(p).read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("id"):
            loaded.append((p, data))
    return loaded


def dedup(paths: list[Path], config: dict, aliases: list[list[str]] | None = None,
          earlier: list[Path] | None = None) -> list[Path]:
    """Collapse cross-site duplicate postings, returning only canonical paths.

    Parameters
    ----------
    paths:
        List of ``Path`` objects pointing to ``posting.json``-style files
        (returned by ``prefilter()``).
    config:
        Raw profile config dict.  Relevant keys:
        - ``dedup_similarity_threshold`` (float, default 1.0): only exact
          normalised-string matches are collapsed for MVP.
        - ``dedup_source_priority`` (list[str], default []): preferred source
          order when selecting the canonical posting.
    aliases:
        Groups of names of one employer (``[name, *also]`` of each followed
        employer): a posting under any of them is under the group's first name.
    earlier:
        Postings from previous days: the originals of any new copy among *paths* (see the module
        doc). One that is itself a duplicate is left out.

    Returns
    -------
    list[Path]
        Paths to canonical (non-duplicate) postings.  Dropped postings are
        rewritten in-place with duplicate markers.
    """
    if not paths:
        return []

    source_priority: list[str] = config.get("dedup_source_priority", [])

    references = [item for item in _load(earlier or []) if not item[1].get("duplicate_of")]
    loaded = references + _load(paths)
    n_earlier = len(references)

    # Group by normalised key, merging groups that share a tracking-system project.
    parent = list(range(len(loaded)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    same_as = {_normalise(name, ""): group[0] for group in aliases or [] for name in group}
    first_with: dict[str, int] = {}
    for i, (_, data) in enumerate(loaded):
        company = data.get("company", "")
        keys = [_normalise(same_as.get(_normalise(company, ""), company), data.get("title", ""))]
        keys += [k for k in {_project_key(data.get("apply_url") or ""), _project_key(data.get("url") or "")} if k]
        for key in keys:
            if key in first_with:
                parent[find(i)] = find(first_with[key])
            else:
                first_with[key] = i
    groups: dict[int, list[tuple[Path, dict]]] = {}
    seen_before: dict[int, dict] = {}  # group -> its first earlier posting
    for i, item in enumerate(loaded):
        if i < n_earlier:
            seen_before.setdefault(find(i), item[1])
        else:
            groups.setdefault(find(i), []).append(item)

    surviving: list[Path] = []

    for key, group_items in groups.items():
        if len(group_items) == 1 and key not in seen_before:
            # No duplicate — keep as-is
            surviving.append(group_items[0][0])
            continue

        # Select canonical: the earlier posting when there is one
        if key in seen_before:
            canonical_id = seen_before[key]["id"]
        else:
            canonical_id = _pick_canonical([d for _, d in group_items], source_priority)["id"]

        for p, data in group_items:
            if data["id"] == canonical_id:
                surviving.append(p)
            else:
                # Mark as duplicate and rewrite in-place
                data["score"] = 0.0
                data["score_reason"] = "duplicate"
                data["duplicate_of"] = canonical_id
                try:
                    p.write_text(json.dumps(data, indent=2, default=str))
                except OSError:
                    pass  # best-effort write

    return surviving
