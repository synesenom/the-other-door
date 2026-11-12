"""`find`'s five steps, one module each: `search`, `discover`, `follow`, `collect`, `match`.

Each module has a core that returns a dict (its block of the run record) and never prints;
`door.commands.find` composes them. This package holds what they share: the step names and
the progress events a step reports about itself (``stage="step"``, ``site=<step>``), which
`door.pipeline.display` renders.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager

from door.core import progress

STEPS = ("search", "discover", "follow", "collect", "match")


def plan(names) -> None:
    """Announce the steps about to be shown (in order), so a display can list them as waiting."""
    progress.report("plan", stage="steps", detail=",".join(names))


def skipped(name: str, reason: str) -> None:
    progress.report(f"skipped: {reason}", site=name, stage="step", outcome="skipped", detail=reason)


def started(name: str, total: int | None = None) -> None:
    """Report step *name* started (with its *total* of work, if known)."""
    progress.report("started", 0, total, site=name, stage="step", outcome="start")


def finished(name: str, summary: str, failure: str | None = None) -> None:
    """Report step *name* done with *summary*, or failed with *failure*."""
    if failure is not None:
        progress.report(failure, site=name, stage="step", outcome="failed", detail=failure)
    else:
        progress.report(summary, site=name, stage="step", outcome="done", detail=summary)


def items(name: str, pairs) -> None:
    """Announce what step *name* reads, as ``(id, label)`` pairs in order (its boards, its sources); report
    it after the step's start, which clears the list. A board's own ``stage="scrape"`` events mark it."""
    progress.report("items", site=name, stage="items", detail=json.dumps([[i, label] for i, label in pairs]))


def item(name: str, source: str, outcome: str) -> None:
    """Mark *source* of step *name*: ``start``, ``done`` or ``failed``."""
    progress.report(source, site=name, stage="item", outcome=outcome, detail=source)


class _Step:
    def __init__(self, name: str, clock) -> None:
        self.name, self._clock = name, clock
        self.summary = ""
        self.failure: str | None = None
        self.elapsed_s = 0.0

    def fail(self, reason: str) -> None:
        """End the step as failed (not raised) with *reason*."""
        self.failure = reason


@contextmanager
def running(name: str, *, total: int | None = None, clock=time.monotonic, late: bool = False):
    """Report *name* started (with its *total* of work, if known), then done with ``step.summary``,
    or failed with ``step.fail(reason)`` or when the block raises (the error goes on).

    With *late* the step is a second pass over a step that already ended (`find`'s "late follow"
    and "late collect": the employers discover queued while the others ran): the events are
    ``stage="late"`` instead of ``"step"``, so the display folds them into the step's own line."""
    stage = "late" if late else "step"
    step = _Step(name, clock)
    started = clock()
    progress.report("started", 0, total, site=name, stage=stage, outcome="start")
    try:
        yield step
    except BaseException as exc:
        step.elapsed_s = clock() - started
        reason = f"{type(exc).__name__}: {exc}"
        progress.report(reason, site=name, stage=stage, outcome="failed", detail=reason)
        raise
    step.elapsed_s = clock() - started
    if step.failure is not None:
        progress.report(step.failure, site=name, stage=stage, outcome="failed", detail=step.failure)
    else:
        progress.report(step.summary, site=name, stage=stage, outcome="done", detail=step.summary)
