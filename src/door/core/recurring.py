"""Something that keeps going wrong (#593): the one failure the app says, so the user sends a report.

A failure the next run retries is said nowhere (docs/design/README.md, principle 8): it goes to the
problem log (`door.core.problem_log`). The same failure again and again is something the user can act on,
by sending a problem report (`data report`), so `status_summary` says it as ``recurring_problem`` and the
app puts one line at the sidebar's foot. It is read from what is on disk: the run records and the log.

Only what happened after the last saved report counts (`_report_core` stamps `<data folder>/logs/reported_at`),
and each condition clears by itself once the problem stops. The thresholds are the constants below.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from door.core import problem_log, runs

SITE_RUNS = 3  # the same site failed (failed or error) in each of its last 3 tries
SCORING_RUNS = 2  # ads left unscored in each of the last 2 runs that scored
TOOL_FAILURES = 3  # the same tool failed this many times ...
TOOL_WINDOW = timedelta(hours=24)  # ... within the last 24 hours
SERVER_WINDOW = timedelta(days=7)  # the server stopped or would not start in the last 7 days

STAMP = "reported_at"

_FAILED = ("failed", "error")
_NOT_TRIED = ("not_configured", "resting")
_LINE = re.compile(r"^(\S+) ERROR (?:tool (?P<tool>\S+)|app (?P<server>server (?:stopped|would not start))): ")


def _parse(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _when(record: dict) -> datetime | None:
    return _parse(record.get("finished_at")) or _parse(record.get("started_at"))


def _site_keeps_failing(records: list[dict]) -> bool:
    """A site whose last `SITE_RUNS` tries (newest first, runs that rested or skipped it left out) all failed."""
    tries: dict[str, list[str]] = {}
    for record in reversed(records):
        for entry in runs.site_entries(record):
            outcome = entry.get("outcome")
            if outcome in _NOT_TRIED:
                continue
            tries.setdefault(entry.get("site"), []).append(outcome)
    return any(len(t) >= SITE_RUNS and all(o in _FAILED for o in t[:SITE_RUNS]) for t in tries.values())


# A tool refused because the ledgers are busy (`lock.py`'s messages) did not go wrong: it waits its turn.
_BUSY = ("a run is in progress", "is writing the ledgers")


def _scoring_keeps_failing(records: list[dict]) -> bool:
    scored = [r["match"] for r in records if isinstance(r.get("match"), dict)][-SCORING_RUNS:]
    return len(scored) == SCORING_RUNS and all(m.get("failed") for m in scored)


def _log_keeps_failing(lines: list[str], since: datetime | None, now: datetime) -> bool:
    per_tool: dict[str, int] = {}
    for line in lines:
        hit = _LINE.match(line)
        at = _parse(hit.group(1)) if hit else None
        if at is None or (since is not None and at <= since):
            continue
        if hit.group("server") and at >= now - SERVER_WINDOW:
            return True
        if hit.group("tool") and at >= now - TOOL_WINDOW and not any(w in line for w in _BUSY):
            per_tool[hit.group("tool")] = per_tool.get(hit.group("tool"), 0) + 1
            if per_tool[hit.group("tool")] >= TOOL_FAILURES:
                return True
    return False


def keeps_going_wrong(records: list[dict], log_lines: list[str], *, reported_at: datetime | None, now: datetime) -> bool:
    """Whether something keeps going wrong, after `reported_at` (None: never reported). Pure.

    Args:
        records: The run records, oldest first.
        log_lines: The problem log's lines (``<UTC time> <LEVEL> <where>: <message>``).
    """
    after = [r for r in records if reported_at is None or ((_when(r) or reported_at) > reported_at)]
    return _site_keeps_failing(after) or _scoring_keeps_failing(after) or _log_keeps_failing(log_lines, reported_at, now)


def reported_at(home: Path) -> datetime | None:
    """When a problem report was last saved from this data folder, or None."""
    try:
        return _parse((Path(home) / problem_log.FOLDER / STAMP).read_text(encoding="utf-8").strip())
    except OSError:
        return None


def stamp_report(home: Path, at: datetime | None = None) -> None:
    """Remember that a report was saved now: what went wrong before it is said no more."""
    home = Path(home)
    if not home.is_dir():
        return
    folder = home / problem_log.FOLDER
    folder.mkdir(exist_ok=True)
    (folder / STAMP).write_text((at or datetime.now(timezone.utc)).isoformat(), encoding="utf-8")


def check(home: Path, records: list[dict], *, now: datetime | None = None) -> bool:
    """`keeps_going_wrong` for the data folder `home` (its `logs/door.log` and `logs/reported_at`)."""
    log = Path(home) / problem_log.FOLDER / problem_log.FILE
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    return keeps_going_wrong(records, lines, reported_at=reported_at(home), now=now or datetime.now(timezone.utc))
