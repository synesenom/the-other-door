"""What `find` shows while it works: one line per step.

Three parts, none of which prints from a core:

* `BoardState` folds the progress events (`door.core.progress`) into a view of the five steps;
  `render_lines` is a pure function from that view to the lines drawn: ``○`` waiting, a yellow
  spinner while running (with a bar and counts), green ``✓`` done (summary and elapsed time),
  red ``✗`` failed, grey ``–`` skipped (with the reason).
* `StepBoard` is the `Reporter` that redraws those lines in place on a terminal.
* `PlainSteps` is the `Reporter` for a pipe or a log: one line as each step ends,
  ``[4/5] collect: 158 employers, 2,431 postings, 2 failed (41m)``.

The events (see `door.pipeline`): ``stage="steps"`` ``message="plan"`` with
``detail="search,discover,..."`` once; ``stage="step"`` with ``site=<step>`` and ``outcome`` start
(with ``total``), done, failed or skipped (``detail`` = summary or reason). Inside a running step,
the events of its work: ``items`` (``detail`` = JSON ``[[id, label], ...]``: what the step reads, listed
waiting; the app draws them under the bar, the terminal does not), ``scrape`` (a board starts, or ends
with its ``outcome``: ok and empty check it, a site not read at all, resting, reserved or not configured,
leaves the list, any other fails it; search's count is its boards finished of those listed), ``postings``
(a board's or feed's running count), ``keyword_search`` / ``ad_details`` (a board at work: message = the
keyword, ``done``/``total`` = keyword N of M / ad N of the keyword's M; kept on the board's item as its
``activity`` until the board ends), ``candidate`` (follow), ``entry_start`` / ``entry_end`` (an
employer's request group, message = host), and match's ``scored`` / ``scoring`` and pass names.

`discover` runs in the background beside the others, so its events never go to "the running step"
(the ``li_*`` stages are the generic stage names of every discovery source, not LinkedIn's alone; the site
is the discriminator):
``item`` (``detail`` = a source of its ``items``, outcome start, done or failed),
``li_request`` (message "page 3/15" / "job page 12/15", ``done``/``total`` = requests made / budget)
``li_wait`` (``done`` = seconds of pause that begin now, drawn as a countdown) and ``li_end`` (how its
requests ended, outcome done or failed: the line is finished there, and the step's own done event,
when `find` has queued its result, only replaces the text) always belong to its line, and the work events of the other steps skip it. A second pass over a step that already ended (``stage="late"``, ``site=<step>``, outcome start / done / failed: the late follow and late
collect for the employers discover queued) turns the finished line back into a running one, then
into a done one whose summary ends in ``+ late: <summary>``: the five lines stay five.
"""

from __future__ import annotations

import itertools
import json
import re
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import click

from door.core.progress import Progress

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_NAME_WIDTH = 8
_BAR = 10
_MAX_HOSTS = 3
_FAILED = re.compile(r"\b\d+ failed\b")
_NOT_READ = {"resting", "reserved", "not_configured"}
_ACTIVITIES = {"keyword_search": "searching", "ad_details": "reading"}
_PASSES = {"prefilter", "dedup", "language", "condense", "prescreen", "liveness"}


def format_elapsed(seconds: float) -> str:
    """``12s``, ``4m12s``, ``41m``, ``1h05m``."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"


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


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _bar(done: int, total: int | None) -> str:
    if not total:
        return ""
    filled = min(_BAR, int(_BAR * done / total))
    return "█" * filled + "░" * (_BAR - filled)


def _progress_text(view: StepView, now: float = 0.0) -> str:
    """The counts of a running step, after its bar."""
    name = view.name
    postings = ", ".join(f"{site} {n}" for site, n in view.postings.items())
    late = "late " if view.late else ""
    if name == "discover":
        parts = [view.request] if view.request else []
        if view.wait_until > now:
            parts.append(f"waiting {int(view.wait_until - now + 0.5)} s")
        return " · ".join(parts)
    if name == "search":
        counts = f"{view.done}/{view.total} boards" if view.total else _plural(view.done, "board", "boards")
        doing = [f"{it.id}: {_activity_text(it.activity)}" for it in view.items if it.state == "running" and it.activity]
        return " · ".join([counts, *([postings] if postings else []), *doing])
    if name == "follow":
        return f"{late}{view.done}/{view.total} candidates" if view.total else f"{late}{view.done} candidates"
    if name == "collect":
        parts = [f"{late}{view.done}/{view.total} employers" if view.total else f"{late}{view.done} employers",
                 f"{sum(view.postings.values()):,} postings"]
        if view.hosts:
            parts.append(", ".join(view.hosts[:_MAX_HOSTS]))
        return " · ".join(parts)
    if name == "match":
        if view.total:
            return f"{view.done}/{view.total} scored"
        return view.phase
    return ""


def _activity_text(activity: dict) -> str:
    """``reading ads for 'data' (12 of 40)`` / ``searching 'data' (keyword 3 of 21)``."""
    keyword, done, total = activity.get("keyword", ""), activity.get("done", 0), activity.get("total", 0)
    if activity.get("kind") == "reading":
        return f"reading ads for '{keyword}' ({done} of {total})"
    return f"searching '{keyword}' (keyword {done} of {total})"


def _fit(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(width - 1, 1)] + "…"


def render_lines(state: BoardState, *, frame: str, now: float, width: int = 100, color: bool = True) -> list[str]:
    """One line per step of the plan: ``○`` waiting, *frame* (a spinner frame) running, ``✓``
    done, ``✗`` failed, ``–`` skipped. Pure; *now* is the clock of `BoardState.apply`, *width*
    cuts a long line with an ellipsis."""
    def paint(text: str, fg: str) -> str:
        return click.style(text, fg=fg) if color else text

    out = []
    for view in state.steps.values():
        name = view.name.ljust(_NAME_WIDTH)
        if view.status == "waiting":
            out.append(f"{paint('○', 'bright_black')} {view.name}")
            continue
        if view.status == "running":
            body = _progress_text(view, now)
            if view.name == "discover":
                made = view.requests[0] if view.requests else 0
                bar = _bar(made, view.requests[1] if view.requests else view.total)
            else:
                bar = _bar(view.done, view.total)
            text = "  ".join(x for x in (bar, body) if x)
            line = _fit(f"{frame} {name}  {text}".rstrip(), width)
            out.append(f"{paint(line[:1], 'yellow')}{line[1:]}" if color else line)
            continue
        if view.status == "skipped":
            line = _fit(f"– {name}  skipped: {view.detail}".rstrip(), width)
            out.append(f"{paint('–', 'bright_black')}{line[1:]}" if color else line)
            continue
        glyph, fg = ("✓", "green") if view.status == "done" else ("✗", "red")
        suffix = f" ({format_elapsed(view.elapsed)})"
        line = _fit(f"{glyph} {name}  {view.detail}{suffix}", width)
        if color:
            line = paint(glyph, fg) + _FAILED.sub(lambda m: click.style(m.group(0), fg="yellow"), line[1:]) \
                if view.status == "done" else paint(glyph, fg) + line[1:]
        out.append(line)
    return out


class StepBoard:
    """A `Reporter` that draws the step lines on a terminal and redraws them in place.

    Args:
        stream: Where to draw (default: ``sys.stdout``).
        animate: Spin from a background thread (default: whether *stream* is a terminal);
            without it each event redraws synchronously, which is what tests use.
        interval: Seconds between spinner frames.
        clock: Seconds for elapsed times (default: ``time.monotonic``).
    """

    def __init__(self, stream=None, *, animate: bool | None = None, interval: float = 0.1, clock=time.monotonic):
        self._stream = stream if stream is not None else sys.stdout
        isatty = getattr(self._stream, "isatty", lambda: False)
        self._color = bool(isatty())
        self._animate = self._color if animate is None else animate
        self._interval, self._clock = interval, clock
        self._state = BoardState()
        self._frames = itertools.cycle(SPINNER)
        self._lock = threading.Lock()
        self._drawn = 0
        self._stop = threading.Event()
        self._thread = None
        if self._animate:
            self._thread = threading.Thread(target=self._spin, name="step-board", daemon=True)
            self._thread.start()

    def report(self, event: Progress) -> None:
        with self._lock:
            self._state.apply(event, now=self._clock())
            if not self._animate or event.stage in ("steps", "step"):
                self._draw()

    def stop(self) -> None:
        """Stop the spinner and leave the final lines on screen."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        with self._lock:
            self._draw()

    def _draw(self) -> None:
        if not self._state.steps:
            return
        width = shutil.get_terminal_size((100, 24)).columns - 1
        lines = render_lines(self._state, frame=next(self._frames), now=self._clock(), width=width, color=self._color)
        up = f"\033[{self._drawn}A" if self._drawn else ""
        try:
            self._stream.write(up + "".join(f"\r{line}\033[K\n" for line in lines))
            self._stream.flush()
        except (ValueError, OSError):  # a closed terminal must not stop a run
            pass
        self._drawn = len(lines)

    def _spin(self) -> None:
        while not self._stop.wait(self._interval):
            with self._lock:
                self._draw()


class PlainSteps:
    """A `Reporter` that writes one line as each step ends: ``[4/5] collect: <summary> (41m)``."""

    def __init__(self, stream=None, *, clock=time.monotonic):
        self._stream = stream if stream is not None else sys.stdout
        self._clock = clock
        self._plan: list[str] = []
        self._started: dict[str, float] = {}
        self._lock = threading.Lock()

    def report(self, event: Progress) -> None:
        with self._lock:
            if event.stage == "steps" and event.message == "plan":
                self._plan = [n for n in (event.detail or "").split(",") if n]
            elif event.stage == "step" and event.site:
                self._step(event)
            elif event.stage == "late" and event.site and event.outcome in ("done", "failed"):
                self._late(event)

    def _late(self, event: Progress) -> None:
        name = event.site
        index = self._plan.index(name) + 1 if name in self._plan else 0
        what = event.detail or ""
        text = f"[{index}/{len(self._plan)}] {name} (late): " + (f"failed - {what}" if event.outcome == "failed" else what)
        try:
            self._stream.write(text + "\n")
            self._stream.flush()
        except (ValueError, OSError):
            pass

    def _step(self, event: Progress) -> None:
        name = event.site
        if event.outcome == "start":
            self._started[name] = self._clock()
            return
        if event.outcome not in ("done", "failed", "skipped"):
            return
        index = self._plan.index(name) + 1 if name in self._plan else 0
        head = f"[{index}/{len(self._plan)}] {name}:"
        if event.outcome == "skipped":
            text = f"{head} skipped ({event.detail})"
        else:
            end = self._clock()
            took = format_elapsed(end - self._started.get(name, end))
            what = event.detail or ""
            text = f"{head} failed - {what} ({took})" if event.outcome == "failed" else f"{head} {what} ({took})"
        try:
            self._stream.write(text + "\n")
            self._stream.flush()
        except (ValueError, OSError):
            pass


@contextmanager
def steps_progress(*, tty: bool, stream=None):
    """Yield the `Reporter` to pass to `_find_core` as ``progress=``: a live `StepBoard` on a
    terminal, else `PlainSteps` (one line per step as it ends); always stopped on exit."""
    if tty:
        board = StepBoard(stream)
        try:
            yield board
        finally:
            board.stop()
    else:
        yield PlainSteps(stream)
