#!/usr/bin/env python3
"""Persistent cross-run dedup store for job postings.

Tracks which job ids have been seen, when they were first / last seen,
and supports a ``recheck_after_days`` window to re-surface stale entries.

File format: ``jobs/history.json`` — a JSON object keyed by job id
(``<site>.<platform_id>``, the same key as the posting file, the ledger and
``jobs/output/``):
  {
    "<job_id>": {
      "job_id": "<job_id>",
      "platform_id": "<platform_id>",
      "url": "<url>",
      "source": "<site>",
      "first_seen": "<ISO-8601>",
      "last_seen": "<ISO-8601>",
      "status": "seen"
    },
    ...
  }

Writes are atomic (``utils.write_json_atomic``): a temp file renamed over
the target.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from door.core import utils


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class HistoryStore:
    """Load, query, and persist the cross-run job dedup history.

    Parameters
    ----------
    path:
        Absolute path to ``history.json``.  The file does not need to exist
        yet — it will be created on the first :meth:`save` call.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._data: dict[str, dict] = {}
        self._load()

    # ---------------------------------------------------------------------- #
    # Private helpers
    # ---------------------------------------------------------------------- #

    def _load(self) -> None:
        """Load history from disk.  Silently falls back to ``{}`` on any error."""
        if not self._path.exists():
            return
        try:
            raw = self._path.read_text(encoding="utf-8")
            self._data = json.loads(raw)
        except Exception:
            self._data = {}

    # ---------------------------------------------------------------------- #
    # Public API
    # ---------------------------------------------------------------------- #

    def is_new(
        self,
        job_id: str | None,
        source: str,
        recheck_after_days: int | None,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Return True if the posting should be treated as new / unseen.

        ``job_id=None`` is always treated as new (pass-through).

        Parameters
        ----------
        job_id:
            The posting's id (``<site>.<platform_id>``, ``JobPosting.id``).
        source:
            Site name — reserved for future per-source logic.
        recheck_after_days:
            If set, entries whose ``last_seen`` is older than this many days
            are re-surfaced as new.  ``None`` means never recheck.
        now:
            Override "current time" — used in tests.
        """
        if job_id is None:
            return True

        entry = self._data.get(job_id)
        if entry is None:
            return True

        if recheck_after_days is not None:
            _now = now if now is not None else _utcnow()
            last_seen_str = entry.get("last_seen", "")
            try:
                last_seen = datetime.fromisoformat(last_seen_str)
                age_days = (_now - last_seen).total_seconds() / 86400
                if age_days > recheck_after_days:
                    return True
            except (ValueError, TypeError):
                # Malformed date — treat as new
                return True

        return False

    def known_ids(
        self,
        source: str,
        recheck_after_days: int | None,
        *,
        now: datetime | None = None,
    ) -> set[str]:
        """Return platform_ids for *source* that are "already known" — i.e.
        :meth:`is_new` would return ``False`` for them right now.

        Used to skip an expensive per-posting detail fetch (issue #134):
        entries are excluded once they fall outside ``recheck_after_days``
        (they re-surface as "new" and should be re-fetched), and entries
        recorded under a different ``source`` are never included.
        """
        result: set[str] = set()
        prefix = f"{source}."
        for job_id, entry in self._data.items():
            if entry.get("source") != source:
                continue
            if not self.is_new(job_id, source, recheck_after_days, now=now):
                platform_id = entry.get("platform_id")
                if platform_id is None:  # a legacy entry: the key is ``<source>.<platform_id>``
                    platform_id = job_id[len(prefix):] if job_id.startswith(prefix) else job_id
                result.add(platform_id)
        return result

    def record(
        self,
        job_id: str,
        platform_id: str,
        url: str,
        source: str,
        *,
        now: datetime | None = None,
    ) -> None:
        """Record (or update) a posting in the history.

        ``first_seen`` is set only on the very first record; subsequent calls
        update only ``last_seen``.
        """
        _now = now if now is not None else _utcnow()
        ts = _now.isoformat()

        existing = self._data.get(job_id)
        if existing is None:
            self._data[job_id] = {
                "job_id": job_id,
                "platform_id": platform_id,
                "url": url,
                "source": source,
                "first_seen": ts,
                "last_seen": ts,
                "status": "seen",
            }
        else:
            # Preserve first_seen; update last_seen
            existing["last_seen"] = ts

    def touch(self, job_id: str, *, now: datetime | None = None) -> None:
        """Update ``last_seen`` for a known posting without changing anything else.

        No-op if ``job_id`` is not in the store.
        """
        entry = self._data.get(job_id)
        if entry is None:
            return
        _now = now if now is not None else _utcnow()
        entry["last_seen"] = _now.isoformat()

    def save(self) -> None:
        """Atomically persist history to disk.

        A temp file renamed over the target; the parent directory is created.
        """
        utils.write_json_atomic(self._path, self._data)
