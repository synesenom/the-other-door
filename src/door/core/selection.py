#!/usr/bin/env python3
"""Selection helper — ranked, unapplied job matches (issue #67).

Pure Python, no LLM, no network. Walks ``jobs/postings/<YYYY-MM-DD>/<site>/*.json``,
keeps postings that pass the score threshold and are not yet applied to (per
the application tracker), and returns them sorted by ``score`` descending.

Shared by ``./door list`` and future presentation commands (``show``,
dashboard, ``apply``).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Collection, Iterable, Iterator
from pathlib import Path
from typing import Any

from door.core import tracker as tracker_mod
from door.core import workspace

def date_dirs(jobs_dir: Path) -> list[Path]:
    """The ``jobs/postings/<YYYY-MM-DD>/`` directories, oldest first.

    Day folders an older version left directly under ``jobs/`` are moved there first
    (`workspace.move_day_folders`). Empty when ``jobs_dir`` does not exist.
    """
    workspace.move_day_folders(jobs_dir)
    root = workspace.postings_dir(jobs_dir)
    if not root.is_dir():
        return []
    return [d for d in sorted(root.iterdir()) if d.is_dir() and workspace.DAY_RE.fullmatch(d.name)]


def iter_postings(jobs_dir: Path) -> Iterator[tuple[Path, dict]]:
    """Every readable posting as ``(path, posting)``, in sorted date/site/file order.

    Walks ``jobs/postings/<YYYY-MM-DD>/<site>/*.json`` under `date_dirs`; malformed
    or unreadable JSON files are skipped.
    """
    for date_dir in date_dirs(jobs_dir):
        for json_path in sorted(date_dir.glob("*/*.json")):
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            yield json_path, data


def read_postings(jobs_dir: Path) -> list[dict]:
    """Every readable posting, read once (`iter_postings` without the paths)."""
    return [data for _, data in iter_postings(jobs_dir)]

# Application statuses that mean "already spoken for" — postings whose
# tracked status is anything else (prepared, applied, discarded, …) are excluded.
# Untracked (status is None) and "unapplied" are the only eligible states.
_ELIGIBLE_STATUSES = {None, "unapplied"}


def select_matches(
    jobs_dir: Path,
    tracker: Any,
    min_score: float,
    status: str | Collection[str] | None = None,
    postings: Iterable[dict] | None = None,
) -> list[dict]:
    """Return scored postings that match and are not yet applied to.

    With `status`, instead the postings whose tracked status is that one, or
    any of them when it is a collection (``"unapplied"`` also takes the untracked).

    Parameters
    ----------
    jobs_dir:
        Root ``jobs/`` directory. Only top-level subdirectories named like a
        date (``^\\d{4}-\\d{2}-\\d{2}$``) are walked, so ``jobs/output/`` and
        other non-date directories (e.g. ``runs``) are never scanned.
    tracker:
        An object exposing ``get_status(job_id) -> str | None`` (e.g.
        ``tracker.ApplicationTracker``).
    min_score:
        Minimum ``score`` (inclusive) for a posting to be included. A posting
        with no score (nothing to rank) or a zero score (dropped by the
        prescreen or language pass) is never included.
    postings:
        The postings already read (`read_postings`), so a caller that needs
        several views of them walks ``jobs_dir`` once; read from it when None.

    Returns
    -------
    list[dict]
        Posting dicts sorted by ``score`` descending. Ties keep the order
        encountered while walking the (sorted) date/site/file tree.
    """
    matches: list[dict] = []
    wanted = {status} if isinstance(status, str) else status

    for data in read_postings(jobs_dir) if postings is None else postings:
        score = data.get("score")
        if score is None or score <= 0 or score < min_score:
            continue
        tracked = tracker.get_status(data.get("id"))
        if wanted is None:
            if tracked not in _ELIGIBLE_STATUSES:
                continue
        elif (tracked or "unapplied") not in wanted:
            continue

        matches.append(data)

    matches.sort(key=lambda d: d["score"], reverse=True)
    return matches


def find_posting(jobs_dir: Path, job_id: str) -> dict | None:
    """Return the full posting dict for ``job_id``, or ``None`` if not found.

    Walks ``jobs/postings/<YYYY-MM-DD>/<site>/*.json`` the same way ``select_matches``
    does — only date-named top-level directories are scanned, so
    ``jobs/output/`` and similar are never scanned. Malformed JSON files are
    skipped tolerantly. If the same ``job_id`` appears in more than one
    posting file, the first one encountered in sorted walk order (earliest
    date directory first) wins.

    Parameters
    ----------
    jobs_dir:
        Root ``jobs/`` directory.
    job_id:
        The posting's ``id`` field to look up.

    Returns
    -------
    dict | None
        The matching posting dict, or ``None`` if ``jobs_dir`` doesn't exist
        or no posting has this ``job_id``.
    """
    return next((data for _, data in iter_postings(jobs_dir) if data.get("id") == job_id), None)


def find_posting_path(jobs_dir: Path, job_id: str) -> Path | None:
    """Return the file path of the posting for ``job_id``, or ``None`` if not found.

    Walks ``jobs/postings/<YYYY-MM-DD>/<site>/*.json`` identically to
    :func:`find_posting` (same date-directory filter, same sorted walk order,
    same tolerant skipping of malformed JSON and exclusion of
    ``jobs/output/``), but returns the matching JSON file's path instead of
    its parsed contents. Used by callers that write back to the posting
    rather than just read its fields.

    Parameters
    ----------
    jobs_dir:
        Root ``jobs/`` directory.
    job_id:
        The posting's ``id`` field to look up.

    Returns
    -------
    Path | None
        The matching posting JSON file's path, or ``None`` if ``jobs_dir``
        doesn't exist or no posting has this ``job_id``.
    """
    return next((path for path, data in iter_postings(jobs_dir) if data.get("id") == job_id), None)


# Statuses always shown in a ledger breakdown, zero-filled when absent, in
# lifecycle order.
_KNOWN_LEDGER_STATUSES = tracker_mod.STATUSES


def pipeline_summary(
    jobs_dir: Path, tracker: Any, min_score: float, postings: list[dict] | None = None
) -> dict:
    """Aggregate counts across every scraped posting on disk.

    Walks the same date-dir-restricted tree as `select_matches` (so
    `jobs/output/` and other non-date directories are never scanned), but —
    unlike `select_matches` — counts every readable posting regardless of
    score, since the point here is visibility into the whole pipeline, not
    just the currently-actionable subset.

    Parameters
    ----------
    jobs_dir:
        Root ``jobs/`` directory.
    tracker:
        An object exposing ``get_status(job_id) -> str | None``, passed
        through to `select_matches` for the "unapplied" count.
    min_score:
        Minimum ``score`` (inclusive) used for the "above_threshold" count.
    postings:
        The postings already read (`read_postings`); read from ``jobs_dir``
        once when None.

    Returns
    -------
    dict
        ``{"total", "excluded", "applicable", "above_threshold", "unapplied",
        "above_threshold_by_status": {"unapplied", "prepared", "applied",
        "discarded"}}`` — ``applicable`` is every posting scored above 0 (a
        zero is one the prescreen, language pass or exclude list dropped);
        ``above_threshold_by_status`` splits ``above_threshold`` by ledger
        status, ``applied`` counting everything past applying (interview,
        ghosted, offer, rejected).
    """
    total = 0
    excluded = 0
    applicable = 0
    above_threshold = 0
    by_status = {"unapplied": 0, "prepared": 0, "applied": 0, "discarded": 0}

    if postings is None:
        postings = read_postings(jobs_dir)
    for data in postings:
        total += 1

        if data.get("score_reason") == "excluded":
            excluded += 1

        score = data.get("score")
        if score is not None and score > 0:
            applicable += 1
        if score is not None and score >= min_score:
            above_threshold += 1
            status = tracker.get_status(data.get("id"))
            if status in _ELIGIBLE_STATUSES:
                by_status["unapplied"] += 1
            elif status in ("prepared", "discarded"):
                by_status[status] += 1
            else:
                by_status["applied"] += 1

    unapplied = len(select_matches(jobs_dir, tracker, min_score, postings=postings))

    return {
        "total": total,
        "excluded": excluded,
        "applicable": applicable,
        "above_threshold": above_threshold,
        "unapplied": unapplied,
        "above_threshold_by_status": by_status,
    }


def ledger_breakdown(applications: dict) -> dict[str, int]:
    """Tally `jobs/applications.json` entries by status.

    Zero-fills the well-known statuses (`tracker.STATUSES`) so the caller can always print
    a full report, but never raises on an unrecognized status string —
    instead it appends a new key for it (in encounter order), since the
    tracker's own `CANONICAL_STATUSES` doesn't include every status this
    function is asked to display (e.g. "prepared").

    Parameters
    ----------
    applications:
        The raw `{job_id: {"status": ..., "updated_at": ...}}` dict, e.g. as
        loaded by `door.commands._common._load_json_tolerant`.

    Returns
    -------
    dict[str, int]
        Counts keyed by status string.
    """
    counts: dict[str, int] = {status: 0 for status in _KNOWN_LEDGER_STATUSES}

    for entry in applications.values():
        status = entry.get("status") if isinstance(entry, dict) else None
        if status is None:
            continue
        counts[status] = counts.get(status, 0) + 1

    return counts


# --------------------------------------------------------------------------- #
# Job references by name (issue #312)
# --------------------------------------------------------------------------- #

# A job with one of these statuses is "in play": a name names it before any other posting.
_IN_PLAY = frozenset({"prepared", "applied", "offer", *tracker_mod.INTERVIEW_STATUSES})
_FOLD = str.maketrans({"ø": "o", "æ": "ae", "å": "a", "ß": "ss", "đ": "d", "ł": "l"})


class AmbiguousJobRef(ValueError):
    """Several jobs match a reference; ``candidates`` lists them, best first, as
    ``{"job_id", "title", "company", "status"}``."""

    def __init__(self, ref: str, candidates: list[dict]):
        self.ref, self.candidates = ref, candidates
        names = "; ".join(f"{c['title']} — {c['company']} ({c['job_id']})" for c in candidates[:10])
        super().__init__(f"{len(candidates)} jobs match {ref!r}: {names}. Say which one (more words, or the job id).")


def _words(text: str) -> list[str]:
    """Lower-case words without accents ("Flügger" → "flugger", "Bagsværd" → "bagsvaerd"). Pure."""
    folded = unicodedata.normalize("NFKD", (text or "").casefold().translate(_FOLD))
    return re.findall(r"\w+", "".join(c for c in folded if not unicodedata.combining(c)))


def _names(ref_words: list[str], posting: dict) -> bool:
    """Whether every word of the reference starts a word of the posting's company, title or English title. Pure."""
    words = _words(" ".join(str(posting.get(k) or "") for k in ("company", "title", "title_en")))
    return all(any(w.startswith(r) for w in words) for r in ref_words)


def resolve_job_ref(ref: str, jobs_dir: Path) -> str:
    """A job reference -> job id.

    An exact job id (a posting's or a ledger entry's) is itself. Otherwise every word of
    *ref* must start a word of the job's company, title or English title (case and
    accents ignored): the jobs in play (prepared, applied, interviewing, offer) are
    searched first, then every other posting that is neither discarded nor a duplicate,
    best score first. One match is the answer; several raise `AmbiguousJobRef` with the
    candidates. A one-word reference nothing matches is passed through as an id.

    Raises:
        AmbiguousJobRef: several jobs match.
        ValueError: nothing matches, or no reference.
    """
    from door.core.utils import _validate_job_id

    text = (ref or "").strip()
    if not text:
        raise ValueError("no job given: name it by company and title words, e.g. 'trustpilot data'")
    jobs_dir = Path(jobs_dir)
    try:
        ledger = json.loads((jobs_dir / "applications.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ledger = {}
    statuses = {job_id: entry.get("status") for job_id, entry in ledger.items() if isinstance(entry, dict)}
    if text in statuses or find_posting_path(jobs_dir, text) is not None:
        return text

    ref_words = _words(text)
    in_play: list[dict] = []
    others: list[dict] = []
    seen: set[str] = set()
    for _path, posting in iter_postings(jobs_dir):
        job_id = str(posting.get("id") or "")
        if not job_id or job_id in seen or not _names(ref_words, posting):
            continue
        seen.add(job_id)
        status = statuses.get(job_id)
        if status in _IN_PLAY:
            in_play.append(posting)
        elif status != "discarded" and not posting.get("duplicate_of"):
            others.append(posting)
    found = in_play or sorted(others, key=lambda p: -(p.get("score") or 0.0))
    if len(found) == 1:
        return str(found[0]["id"])
    if found:
        raise AmbiguousJobRef(text, [
            {"job_id": p["id"], "title": p.get("title") or "", "company": p.get("company") or "",
             "status": statuses.get(p["id"]) or "unapplied"} for p in found
        ])
    if not any(c.isspace() for c in text):
        _validate_job_id(text)
        return text  # one word nothing matches: read as an id (the caller says when no posting has it)
    raise ValueError(f"no job matches {text!r}: name it by words from its company and title")
