#!/usr/bin/env python3
"""Application tracker — persistent ledger for job application statuses.

Tracks which job postings have been applied to, their current status, and
guards against duplicate submissions.

File format: ``jobs/applications.json`` — a JSON object keyed by job_id:
  {
    "<job_id>": {
      "status": "<canonical_status>",
      "updated_at": "<iso>",
      "notes": "...",              # optional, the latest change's
      "materials": {file: sha},    # optional, what was sent (jobs/output/<id>/sent/)
      "history": [{"status", "at", "notes"?, "logged_at"?}, ...]
    },
    ...
  }

Every change is appended to ``history``, so the ledger remembers how an
application went, not only where it is. An event's ``at`` is when it
happened: a change recorded later (``set_status(at=...)``) keeps when it
was logged in ``logged_at`` and goes into the history in date order, so
the history stays a timeline. An interview round is a status of
its own, ``interview:<stage>`` (one per :data:`INTERVIEW_STAGES`), so the
history reads as the rounds in order; a ``rejected``/``ghosted`` ends the
last one. :meth:`ApplicationTracker.interview_rounds` and
:func:`interview_outcomes` read it back as rounds passed, failed or pending;
:func:`application_outcomes` does the same for the application itself (did it
lead to an interview), and :func:`pass_rate` turns either into a rate with its
binomial error.

Writes are atomic (``utils.write_json_atomic``): a temp file renamed over
the target.

Canonical statuses (:data:`STATUSES`, in this order)
-----------------------------------------------------
- ``unapplied``              — identified but not acted on
- ``prepared``               — materials generated, not yet submitted
- ``applied``                — application submitted
- ``interview:screening``    — pre-screening: recruiter / HR call
- ``interview:impression``   — first non-technical interview
- ``interview:assessment``   — personality or cognitive test
- ``interview:technical``    — technical interview, case or take-home
- ``ghosted``                — the company stopped answering mid-process (no reply, no rejection)
- ``rejected``               — application was rejected
- ``offer``                  — offer received
- ``discarded``              — manually discarded / no longer of interest

Lifecycle: ``unapplied -> prepared -> applied -> interview:* -> offer``,
with ``rejected``/``ghosted``/``discarded`` as off-ramps reachable from any
state (a ghosted application can still move on if the company answers after
all).
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from door.core import utils

# The kinds of interview round; each is the status ``interview:<stage>``.
INTERVIEW_STAGES: tuple = (
    "screening",   # pre-screening: recruiter / HR call
    "impression",  # first non-technical interview, often with the hiring manager
    "assessment",  # personality or cognitive test
    "technical",   # technical interview, live coding, case or take-home
)
INTERVIEW_STATUSES: tuple = tuple(f"interview:{stage}" for stage in INTERVIEW_STAGES)

# Every status, in lifecycle order: what `jobs status <job>` offers.
STATUSES: tuple = ("unapplied", "prepared", "applied", *INTERVIEW_STATUSES, "ghosted", "rejected", "offer", "discarded")
CANONICAL_STATUSES: frozenset = frozenset(STATUSES)

# How the last round went, by the application's current status.
_LAST_ROUND_RESULT = {"offer": "passed", "rejected": "rejected", "ghosted": "ghosted", "discarded": "withdrawn"}
ROUND_RESULTS: tuple = ("passed", "rejected", "ghosted", "withdrawn", "pending")

# Statuses that mean the application was sent (with any ``interview:*``).
_SENT_STATUSES: frozenset = frozenset({"applied", "rejected", "ghosted", "offer"})

# The z of the pass rate's Wilson interval: one sigma, ~68%.
PASS_RATE_Z: float = 1.0

# Statuses of a posting still in play: materials made, applied, interviewing, offered.
ONGOING_STATUSES: frozenset = frozenset({"prepared", "applied", *INTERVIEW_STATUSES, "offer"})
# The statuses an application ends in; `discarded` counts only for one that was in play first
# (a match dismissed with "not for me" was never an application).
CLOSED_STATUSES: frozenset = frozenset({"rejected", "ghosted", "discarded"})


def interview_stage(status: str | None) -> str | None:
    """The stage of an ``interview:<stage>`` status, else None."""
    if status and status.startswith("interview:"):
        return status.split(":", 1)[1]
    return None


def is_sent(status: str | None) -> bool:
    """Whether ``status`` means the application was sent: ``applied`` or anything after it."""
    return status in _SENT_STATUSES or interview_stage(status) is not None


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _utc(moment: datetime) -> datetime:
    """``moment`` with a timezone; a naive one is read as UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def parse_at(text: str) -> datetime:
    """When an event happened, from ``YYYY-MM-DD`` or an ISO datetime (naive is UTC).

    Raises:
        ValueError: neither.
    """
    try:
        return _utc(datetime.fromisoformat(text.strip()))
    except ValueError:
        raise ValueError(f"{text!r} is not a date: give YYYY-MM-DD (or YYYY-MM-DDTHH:MM)") from None


def _parsed(at: str | None) -> datetime | None:
    try:
        return _utc(datetime.fromisoformat(at)) if at else None
    except ValueError:
        return None


def is_actionable(status: str | None) -> bool:
    """True if a job is still actionable by a future selection/list command.

    A job is actionable when it is untracked (``status is None``) or still
    ``"unapplied"``. Anything past ``unapplied`` in the lifecycle — including
    ``"prepared"`` — has already been acted upon and is excluded. This is
    the single source of truth for "unapplied/actionable" used by the
    ranked ``list``/dashboard selection logic.
    """
    return status is None or status == "unapplied"


class DuplicateApplicationError(ValueError):
    """Raised when attempting to submit a second application for the same job.

    This is a subclass of ``ValueError`` so a single ``except ValueError``
    in the CLI covers both unknown-status and duplicate-submission errors.
    """


class ApplicationTracker:
    """Load, query, and persist the application status ledger.

    Parameters
    ----------
    path:
        Absolute path to ``applications.json``.  The file does not need to
        exist yet — it will be created on the first :meth:`save` call.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._data: dict[str, dict] = {}
        self._load()

    # ---------------------------------------------------------------------- #
    # Private helpers
    # ---------------------------------------------------------------------- #

    def _load(self) -> None:
        """Load the ledger from disk.  Silently falls back to ``{}`` on any error."""
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

    def set_status(
        self,
        job_id: str,
        status: str,
        *,
        now: datetime | None = None,
        notes: str | None = None,
        at: datetime | None = None,
        materials: dict[str, str] | None = None,
    ) -> None:
        """Set the application status for a job, appending it to its history.

        Parameters
        ----------
        job_id:
            The slug identifier for the job (e.g. ``"jobindex-acme-accountant"``).
        status:
            One of the :data:`CANONICAL_STATUSES`.
        now:
            Override "current time" for the recorded ``updated_at`` — used in
            tests.
        notes:
            Optional free-text note stored with the entry (e.g. why a job
            was discarded, what an interview covered). A later status change
            without one drops it (the history keeps it).
        at:
            When it happened, if not now (a change recorded afterwards; naive
            is UTC). The event keeps ``now`` as ``logged_at`` and goes into the
            history in date order: an event dated before the latest one does
            not change the current status.
        materials:
            ``{file: sha256}`` of the materials sent; kept through later changes.

        Raises
        ------
        ValueError:
            If ``status`` is not in :data:`CANONICAL_STATUSES` or ``at`` is in
            the future.
        DuplicateApplicationError:
            If the job already has status ``"applied"`` and the new status is
            also ``"applied"`` — duplicate submission guard.
        """
        if status not in CANONICAL_STATUSES:
            raise ValueError(f"unknown status {status!r}; must be one of {', '.join(STATUSES)}")

        current_status = self._data.get(job_id, {}).get("status")
        if current_status == "applied" and status == "applied":
            raise DuplicateApplicationError(
                f"job {job_id!r} was already applied to; use a different status to advance it"
            )

        _now = now if now is not None else _utcnow()
        event = {"status": status, "at": _now.isoformat()}
        if at is not None:
            at = _utc(at)
            if at > _now:
                raise ValueError(f"{at.date().isoformat()} is in the future")
            event = {"status": status, "at": at.isoformat(), "logged_at": _now.isoformat()}
        if notes:
            event["notes"] = notes

        history = self.history(job_id)
        when = at or _now
        position = len(history)  # after every event not later than this one (an unreadable date counts as not later)
        while position and (_parsed(history[position - 1].get("at")) or when) > when:
            position -= 1
        history.insert(position, event)

        previous = self._data.get(job_id, {})
        latest = history[-1]
        entry = {"status": latest["status"], "updated_at": latest["at"]}
        if latest.get("notes"):
            entry["notes"] = latest["notes"]
        if materials or previous.get("materials"):
            entry["materials"] = materials or previous["materials"]
        entry["history"] = history
        self._data[job_id] = entry

    def advance(self, job_id: str, to: str, *, now: datetime | None = None) -> None:
        """Advance a job to a new lifecycle status.

        This is a semantic alias for :meth:`set_status`, intended for
        pipeline call sites (e.g. ``prepare``) that
        want to express "move this job forward in the lifecycle" rather
        than "set an arbitrary status". It delegates entirely to
        :meth:`set_status`, so it inherits the same validation and the
        duplicate-``applied`` submission guard verbatim.

        Parameters
        ----------
        job_id:
            The slug identifier for the job.
        to:
            The status to advance to — one of :data:`CANONICAL_STATUSES`.
        now:
            Override "current time" for the recorded ``updated_at``.

        Raises
        ------
        ValueError:
            If ``to`` is not in :data:`CANONICAL_STATUSES`.
        DuplicateApplicationError:
            If the job already has status ``"applied"`` and ``to`` is also
            ``"applied"``.
        """
        self.set_status(job_id, to, now=now)

    def get_status(self, job_id: str) -> str | None:
        """Return the current status for a job, or ``None`` if not tracked."""
        return self._data.get(job_id, {}).get("status")

    def updated_at(self, job_id: str) -> str | None:
        """When the current status happened (ISO), or ``None`` if not tracked."""
        return self._data.get(job_id, {}).get("updated_at")

    def materials(self, job_id: str) -> dict[str, str] | None:
        """``{file: sha256}`` of the materials sent, if recorded."""
        return self._data.get(job_id, {}).get("materials")

    def history(self, job_id: str) -> list[dict]:
        """Every status change of a job, oldest first: ``[{"status", "at", "notes"?, "logged_at"?}, ...]``."""
        entry = self._data.get(job_id)
        if not entry:
            return []
        return list(entry.get("history") or [_event(entry.get("updated_at"), entry)])

    def interview_rounds(self, job_id: str) -> list[dict]:
        """A job's interview rounds in order, each with how it went.

        Every round but the last was passed (the process went on); the last
        one's result follows the current status (``offer`` passed it,
        ``rejected``/``ghosted`` ended there, ``discarded`` withdrew from it,
        anything else is ``pending``). Each round's ``notes`` are the
        notes given with it and with how it ended.

        Returns:
            ``[{"stage", "result", "at", "notes"}, ...]``.
        """
        rounds: list[dict] = []
        for event in self.history(job_id):
            stage = interview_stage(event.get("status"))
            if stage:
                rounds.append({"stage": stage, "result": "passed", "at": event.get("at"), "notes": []})
            if rounds and event.get("notes") and (stage or event.get("status") in _LAST_ROUND_RESULT):
                rounds[-1]["notes"].append(event["notes"])
        if rounds:
            rounds[-1]["result"] = _LAST_ROUND_RESULT.get(self.get_status(job_id), "pending")
        return rounds

    def timeline(self, job_id: str) -> list[dict]:
        """Every status change of a job, oldest first, each interview round with
        how it went (its ``result``, as in :meth:`interview_rounds`).

        Returns:
            ``[{"status", "at", "notes"?, "result"?}, ...]``.
        """
        results = iter(r["result"] for r in self.interview_rounds(job_id))
        return [
            {**event, "result": next(results)} if interview_stage(event.get("status")) else dict(event)
            for event in self.history(job_id)
        ]

    def job_ids(self) -> list[str]:
        """Every job in the ledger."""
        return list(self._data)

    def save(self) -> None:
        """Atomically persist the ledger to disk.

        A temp file renamed over the target; the parent directory is created.
        """
        utils.write_json_atomic(self._path, self._data)


def _event(at: str | None, entry: dict) -> dict:
    """One history event from a ledger entry's fields."""
    event = {"status": entry.get("status"), "at": at}
    if entry.get("notes"):
        event["notes"] = entry["notes"]
    return event


def interview_outcomes(tracker: ApplicationTracker) -> dict[str, dict[str, int]]:
    """How each kind of interview has gone across every application.

    Returns:
        ``{stage: {"passed", "rejected", "ghosted", "withdrawn", "pending"}}``
        for the stages that occur, in :data:`INTERVIEW_STAGES` order.
    """
    counts: dict[str, dict[str, int]] = {}
    for job_id in tracker.job_ids():
        for round_ in tracker.interview_rounds(job_id):
            counts.setdefault(round_["stage"], dict.fromkeys(ROUND_RESULTS, 0))[round_["result"]] += 1
    return {stage: counts[stage] for stage in INTERVIEW_STAGES if stage in counts}


def _application_result(tracker: ApplicationTracker, job_id: str) -> str | None:
    """How one application went (a :data:`ROUND_RESULTS` key), or None if it was never sent."""
    statuses = [event.get("status") for event in tracker.history(job_id)]
    if not any(is_sent(s) for s in statuses):
        return None
    if any(s == "offer" or interview_stage(s) for s in statuses):
        return "passed"
    return _LAST_ROUND_RESULT.get(tracker.get_status(job_id), "pending")


def application_outcomes(tracker: ApplicationTracker) -> dict[str, int]:
    """How the sent applications have gone: whether each led to an interview.

    An application is sent once its history has ``applied``, an interview
    round, ``rejected``, ``ghosted`` or ``offer``. It passed when an interview
    round or an offer followed (even after a ghosting); otherwise its current
    status says how it ended (as for an interview's last round), or it is
    ``pending``.

    Returns:
        ``{"passed", "rejected", "ghosted", "withdrawn", "pending"}``.
    """
    counts = dict.fromkeys(ROUND_RESULTS, 0)
    for job_id in tracker.job_ids():
        result = _application_result(tracker, job_id)
        if result is not None:
            counts[result] += 1
    return counts


def pass_rate(counts: dict[str, int], z: float = PASS_RATE_Z) -> dict:
    """The pass rate of one stage from its outcome counts, with its binomial error.

    Only decided rounds count: passed against rejected or ghosted; withdrawn
    and pending ones are left out. The error is the Wilson score interval at
    `z` (one sigma by default), which stays inside [0, 1] and does not
    collapse to zero width at 0 or 100% the way ``sqrt(p(1-p)/n)`` does.

    Returns:
        ``{"passed", "decided", "rate", "low", "high"}``; ``rate``, ``low``
        and ``high`` are None until a round is decided.
    """
    passed = counts.get("passed", 0)
    decided = passed + counts.get("rejected", 0) + counts.get("ghosted", 0)
    if not decided:
        return {"passed": passed, "decided": 0, "rate": None, "low": None, "high": None}
    p = passed / decided
    denominator = 1 + z * z / decided
    centre = (p + z * z / (2 * decided)) / denominator
    half = z / denominator * math.sqrt(p * (1 - p) / decided + z * z / (4 * decided * decided))
    return {"passed": passed, "decided": decided, "rate": p,
            "low": max(0.0, centre - half), "high": min(1.0, centre + half)}
