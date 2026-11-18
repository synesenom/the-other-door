"""The fold of progress events into the view of `find`'s steps (`BoardState`).

Pure, no output: `core.progress.ProgressFile` writes its `steps` to `jobs/.progress.json` and
`door.pipeline.display` draws it. The events and their meaning are described in
`door.pipeline.display`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from door.core.progress import Progress

_NOT_READ = {"resting", "reserved", "not_configured"}
_ACTIVITIES = {"keyword_search": "searching", "ad_details": "reading"}
_PASSES = {"prefilter", "dedup", "language", "condense", "prescreen", "liveness"}


@dataclass
class StepItem:
    """A board or source a step reads: ``waiting``, ``running``, ``done`` or ``failed``."""
    id: str
    label: str
    state: str = "waiting"
    # what a running board is doing: {"kind": "searching" | "reading", "keyword", "done", "total"}
    activity: dict | None = None


@dataclass
class StepView:
    name: str
    status: str = "waiting"  # waiting | running | done | failed | skipped
    detail: str = ""
    started: float = 0.0
    elapsed: float = 0.0
    done: int = 0
    total: int | None = None
    requests: tuple[int, int] | None = None  # discover: (made, budget)
    request: str = ""  # discover: "page 3/15"
    wait_until: float = 0.0  # discover: the clock time the current pause ends
    late: bool = False  # a late pass is running
    base_detail: str = ""  # the summary the step ended with before its late pass
    postings: dict[str, int] = field(default_factory=dict)
    hosts: list[str] = field(default_factory=list)  # in flight, oldest first
    phase: str = ""
    items: list[StepItem] = field(default_factory=list)  # what it reads, in order

    def mark(self, item_id: str, state: str | None) -> None:
        """Set an item's state, or drop it (*state* None); an id not listed is ignored."""
        for i, it in enumerate(self.items):
            if it.id == item_id:
                if state is None:
                    del self.items[i]
                else:
                    it.state = state
                    if state != "running":
                        it.activity = None
                break
        self.count_items()

    def count_items(self) -> None:
        """Search's progress is its boards: those finished of those read (one not read leaves both)."""
        if self.name == "search" and self.items:
            self.done = sum(1 for it in self.items if it.state in ("done", "failed"))
            self.total = len(self.items)


def _item_state(outcome: str | None) -> str | None:
    """The state a board's ``scrape`` event gives it; None: it is not read at all."""
    if outcome is None:
        return "running"
    if outcome in _NOT_READ:
        return None
    return "done" if outcome in ("ok", "empty") else "failed"


class BoardState:
    """The steps of a run as the events so far describe them."""

    def __init__(self) -> None:
        self.steps: dict[str, StepView] = {}

    def apply(self, event: Progress, *, now: float) -> None:
        if event.stage == "steps" and event.message == "plan":
            for name in (event.detail or "").split(","):
                if name:
                    self.steps.setdefault(name, StepView(name))
            return
        if event.stage == "step" and event.site:
            self._step_event(event, now)
            return
        if event.stage == "late" and event.site:
            self._late_event(event, now)
            return
        if event.stage == "items" and event.site in self.steps:
            self.steps[event.site].items = _items(event.detail)
            self.steps[event.site].count_items()
            return
        if event.stage == "item" and event.site in self.steps:
            self.steps[event.site].mark(event.detail or event.message, "running" if event.outcome == "start" else event.outcome)
            return
        if event.stage in ("li_request", "li_wait", "li_end"):
            view = self.steps.get("discover")
            if view is not None and view.status == "running":
                self._discover_event(view, event, now)
            return
        # `discover` runs beside the others: the work events belong to the step in front of it
        running = next((s for s in self.steps.values() if s.status == "running" and s.name != "discover"), None)
        if running is not None:
            self._work_event(running, event)

    @staticmethod
    def _discover_event(view: StepView, event: Progress, now: float) -> None:
        if event.stage == "li_request":
            view.requests, view.request, view.wait_until = (event.done or 0, event.total or 0), event.message, 0.0
        elif event.stage == "li_end":
            view.status, view.detail, view.elapsed = event.outcome or "done", event.message, now - view.started
        else:
            view.wait_until = now + (event.done or 0)

    def _late_event(self, event: Progress, now: float) -> None:
        view = self.steps.get(event.site)
        if view is None:
            return
        if event.outcome == "start":
            view.base_detail = view.base_detail or view.detail
            view.status, view.late = "running", True
            view.done, view.total, view.hosts, view.postings, view.phase = 0, event.total, [], {}, ""
        elif event.outcome in ("done", "failed"):
            note = f"late: {event.detail}" if event.outcome == "done" else f"late failed: {event.detail}"
            view.status, view.late = "done", False
            view.detail = f"{view.base_detail} + {note}"
            view.elapsed = now - view.started

    def _step_event(self, event: Progress, now: float) -> None:
        view = self.steps.setdefault(event.site, StepView(event.site))
        if event.outcome == "start":
            self.steps[event.site] = StepView(event.site, "running", started=now, total=event.total)
        elif event.outcome in ("done", "failed"):
            if view.status not in ("done", "failed"):  # discover is over when its requests are: keep that time
                view.elapsed = now - view.started
            view.status, view.detail = event.outcome, event.detail or ""
        elif event.outcome == "skipped":
            view.status, view.detail = "skipped", event.detail or ""

    @staticmethod
    def _work_event(view: StepView, event: Progress) -> None:
        stage = event.stage
        if stage == "scrape" and event.site:
            view.mark(event.site, _item_state(event.outcome))
        elif stage in _ACTIVITIES and event.site:
            item = next((it for it in view.items if it.id == event.site), None)
            if item is not None:
                item.activity = {"kind": _ACTIVITIES[stage], "keyword": event.message,
                                 "done": event.done or 0, "total": event.total or 0}
        elif stage == "postings" and event.site:
            view.postings[event.site] = event.done or 0
        elif stage == "candidate":
            view.done, view.total = event.done or 0, event.total
        elif stage == "entry_start":
            view.hosts.append(event.message)
        elif stage == "entry_end":
            view.done += 1
            if event.message in view.hosts:
                view.hosts.remove(event.message)
        elif stage == "match":
            view.done, view.total = event.done or 0, event.total
            view.phase = ""
        elif stage in _PASSES:
            view.phase = event.message


def _items(detail: str | None) -> list[StepItem]:
    try:
        pairs = json.loads(detail or "[]")
        return [StepItem(str(i), str(label)) for i, label in pairs]
    except (ValueError, TypeError):
        return []
