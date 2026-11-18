"""What `find` shows while it works: one line per step.

Three parts, none of which prints from a core:

* `BoardState` (`door.core.board_state`) folds the progress events (`door.core.progress`) into a view of the five steps;
  `render_lines` is a pure function from that view to the lines drawn: ``○`` waiting, a yellow
  spinner while running (with a bar and counts), green ``✓`` done (summary and elapsed time),
  red ``✗`` failed, grey ``–`` skipped (with the reason).
* `StepBoard` is the `Reporter` that redraws those lines in place on a terminal.
* `PlainSteps` is the `Reporter` for a pipe or a log: one line as each step ends,
  ``[4/5] collect: 158 employers, 2,431 postings, 2 failed (41m)``.

The events, and how each one moves a step's line, are described in `door.core.board_state`.
"""

from __future__ import annotations

import itertools
import re
import shutil
import sys
import threading
import time
from contextlib import contextmanager

import click

from door.core.board_state import BoardState, StepView
from door.core.progress import Progress

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_NAME_WIDTH = 8
_BAR = 10
_MAX_HOSTS = 3
_FAILED = re.compile(r"\b\d+ failed\b")


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
