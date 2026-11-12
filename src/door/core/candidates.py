"""The candidates queue: ``jobs/candidates.json``, the employers `follow` has yet to look at.

``{company_key: {"name", "links", "titles", "sources", "first_seen", "last_seen", "name_tried"?}}``, keyed by
`companies.name_key` of the name. `search` adds the employer and apply link of every posting it
writes, `discover` adds the employers LinkedIn shows (an entry whose only links are LinkedIn's
still *needs an apply link*: `follow` first tries the employer by name and, when that finds no
feed, marks it ``name_tried`` and leaves it queued; `discover` then reads its job page when its
request budget allows); `follow` removes the entries it recorded in ``profile/companies.json`` and drops the
ones not seen for ``max_age_days``. A LinkedIn entry also carries ``job_ids`` (the cards it was
seen on). Pure helpers over a dict, plus the atomic load/save; the caller holds the ledger lock
while it writes.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from door.core import ats_detect, companies, freshness, utils

FILE = "candidates.json"
_LIST_FIELDS = ("links", "titles", "sources")


def load(jobs_dir: Path) -> dict:
    """The queue, or an empty one when the file is missing or unreadable."""
    try:
        data = json.loads((Path(jobs_dir) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(jobs_dir: Path, queue: dict) -> None:
    utils.write_json_atomic(Path(jobs_dir) / FILE, queue)


def _merge(into: list, items) -> None:
    into.extend(x for x in items if x and x not in into)


def add(
    queue: dict, name: str, *, links, titles, source: str, now: datetime, **extra: list,
) -> None:
    """Queue *name* (or merge into its entry): links, titles and the *source* that saw it are
    appended without duplicates, ``last_seen`` moves to *now*. *extra* are further list fields
    (``job_ids``) merged the same way. A blank name is ignored."""
    if not name or not name.strip():
        return
    key = companies.name_key(name)
    entry = queue.get(key)
    if entry is None:
        entry = queue[key] = {"name": name.strip(), "links": [], "titles": [], "sources": [],
                              "first_seen": now.isoformat(), "last_seen": now.isoformat()}
    entry["last_seen"] = now.isoformat()
    _merge(entry["links"], links)
    _merge(entry["titles"], titles)
    _merge(entry["sources"], [source])
    for field, values in extra.items():
        _merge(entry.setdefault(field, []), values)


def expire(queue: dict, max_age_days: int | None, now: datetime) -> list[dict]:
    """Remove (in place) and return the entries not seen for more than *max_age_days* (their ads
    have likely closed); ``None`` keeps everything."""
    if max_age_days is None:
        return []
    gone = []
    for key, entry in list(queue.items()):
        seen = freshness._parse_dt(entry.get("last_seen"))
        if seen is not None and now - seen > timedelta(days=max_age_days):
            gone.append(queue.pop(key))
    return gone


def needs_apply_link(entry: dict) -> bool:
    """A LinkedIn employer whose job page was not read yet: it has no link off the job boards."""
    return "linkedin" in (entry.get("sources") or []) and all(
        ats_detect.is_job_board(l) for l in entry.get("links") or [])


def name_tried(entry: dict) -> bool:
    """`follow` already tried this employer by name."""
    return bool(entry.get("name_tried"))


def mark_name_tried(entry: dict, now: datetime) -> None:
    entry["name_tried"] = now.isoformat()


def awaiting_job_page(entry: dict) -> bool:
    """A LinkedIn employer `follow` could not resolve by name and whose job page `discover` has not
    read yet: the only entries that cost a LinkedIn request."""
    return needs_apply_link(entry) and name_tried(entry)
