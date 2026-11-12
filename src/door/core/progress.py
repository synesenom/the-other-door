"""Live progress for the long commands (issue #202).

Cores and scrapers never print: they call `report(message, done, total)` and
whatever surface runs them decides what to do with the events. The CLI draws
a live line, the MCP server forwards them as progress notifications, and the
ledger lock attaches a `ProgressFile` so `status_summary` can answer "how far
is it?" from another process.

The channel is one process-wide stack of active reporters (not thread-local:
the MCP server runs a core in a worker thread and the prepare heartbeat in
another, and both must reach the same reporters). `activate` pushes a reporter
for a block, `scope` fills in `site` / `stage` for every event reported
inside it. The scope, unlike the reporters, is per thread (sites scrape
concurrently, issue #254); a worker thread takes over its parent's with
`current_scope()`. `report()` with no reporter active is a no-op, and a reporter that
raises never stops a scrape.

This module imports nothing from `door.commands` or `door.scrapers`, so
core modules (`liveness`, `lock`) can use it.
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from door.core import utils

PROGRESS_NAME = ".progress.json"
# A board's events whose message is only a keyword: how a line says them.
_STAGE_WORDS = {"keyword_search": "searching '{}'", "ad_details": "reading ads for '{}'"}


@dataclass(frozen=True)
class Progress:
    """One progress event.

    Attributes:
        message: What is happening ("scraping (site 2/5)", "scored").
        done: Items finished so far, if the step counts.
        total: Items in the step, if known.
        site: The job board the event is about, if any.
        stage: The pipeline stage ("scrape", "match", "dedup", "run", ...).
        outcome: Set on the event that closes a site ("ok", "failed", ...).
        detail: A finished step's summary ("158 employers, 2,431 postings"), for
            the events that mark a pipeline step ("start", "done", "failed", "skipped").
    """

    message: str
    done: int | None = None
    total: int | None = None
    site: str | None = None
    stage: str | None = None
    outcome: str | None = None
    detail: str | None = None

    @property
    def text(self) -> str:
        """The message plus its counter: "scored 3/12", "x 2" or just the message.

        An event that closes a site (`outcome` set) is a complete sentence
        ("jobindex: 5 posting(s)"); its counter says which site it was and is
        not appended.
        """
        if self.outcome:
            return self.message
        message = _STAGE_WORDS[self.stage].format(self.message) if self.stage in _STAGE_WORDS else self.message
        if self.done is not None and self.total is not None:
            return f"{message} {self.done}/{self.total}"
        if self.done is not None:
            return f"{message} {self.done}"
        return message

    @property
    def line(self) -> str:
        """`text` prefixed with the site ("jobindex: ..."), unless it already is."""
        if self.site and not self.text.startswith(self.site):
            return f"{self.site}: {self.text}"
        return self.text

    def to_dict(self) -> dict:
        return asdict(self)


class Reporter(Protocol):
    def report(self, event: Progress) -> None: ...


class NullReporter:
    def report(self, event: Progress) -> None:
        return None


class FanOutReporter:
    """Hands every event to each child; a child that raises is skipped."""

    def __init__(self, *reporters: Reporter):
        self._reporters = reporters

    def report(self, event: Progress) -> None:
        for reporter in self._reporters:
            try:
                reporter.report(event)
            except Exception:  # a broken renderer must never stop a scrape
                pass


_state_lock = threading.Lock()
_active: list[Reporter] = []
_local = threading.local()


def current_scope() -> dict:
    """This thread's scope fields, to re-enter in a worker thread: ``with scope(**current_scope())``."""
    return dict(getattr(_local, "scope", {}))


def register(reporter: Reporter) -> None:
    with _state_lock:
        _active.append(reporter)


def unregister(reporter: Reporter) -> None:
    with _state_lock:
        for i, candidate in enumerate(_active):
            if candidate is reporter:
                del _active[i]
                return


@contextmanager
def activate(reporter: Reporter | None):
    """Route events to `reporter` for the block (a no-op for None)."""
    if reporter is None:
        yield None
        return
    register(reporter)
    try:
        yield reporter
    finally:
        unregister(reporter)


@contextmanager
def scope(**fields):
    """Fill in `site` / `stage` / `outcome` for events reported inside the block."""
    previous = current_scope()
    _local.scope = {**previous, **{k: v for k, v in fields.items() if v is not None}}
    try:
        yield
    finally:
        _local.scope = previous


def report(
    message: str,
    done: int | None = None,
    total: int | None = None,
    *,
    site: str | None = None,
    stage: str | None = None,
    outcome: str | None = None,
    detail: str | None = None,
) -> None:
    """Emit a progress event to every active reporter (no-op when none is)."""
    with _state_lock:
        if not _active:
            return
        reporters = tuple(_active)
    ctx = current_scope()
    event = Progress(
        message,
        done,
        total,
        site=site if site is not None else ctx.get("site"),
        stage=stage if stage is not None else ctx.get("stage"),
        outcome=outcome if outcome is not None else ctx.get("outcome"),
        detail=detail,
    )
    FanOutReporter(*reporters).report(event)


class ProgressFile:
    """Mirrors the latest event into `jobs/.progress.json` (throttled).

    The first event, any event that closes a site (`outcome`) and any event
    whose counter has reached its total always write; the rest are written at
    most every `min_interval` seconds. Write failures are swallowed.

    Every event, throttled or not, is also folded into a `pipeline.display.BoardState`
    (on the wall clock, so the times can be written as ISO), and each write carries
    the folded `steps` (see `serialize_steps`): the desktop app draws its run screen
    from them, for a run started anywhere. A fold that raises is ignored.
    """

    def __init__(self, path: Path, *, min_interval: float = 0.25, clock=time.monotonic, wall=time.time):
        # imported here: `pipeline.display` imports this module
        from door.pipeline.display import BoardState

        self._path = Path(path)
        self._min_interval = min_interval
        self._clock = clock
        self._wall = wall
        self._board = BoardState()
        self._last: float | None = None
        self._closed = False
        self._lock = threading.Lock()

    def report(self, event: Progress) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._board.apply(event, now=self._wall())
            except Exception:  # a fold bug must never stop a run
                pass
            now = self._clock()
            final = event.total is not None and event.done is not None and event.done >= event.total
            if (
                self._last is not None
                and event.outcome is None
                and not final
                and now - self._last < self._min_interval
            ):
                return
            self._last = now
            data = {
                **event.to_dict(),
                "steps": serialize_steps(self._board),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
            }
            try:
                utils.write_json_atomic(self._path, data, indent=None)
            except OSError:
                pass

    def close(self) -> None:
        with self._lock:
            self._closed = True


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def serialize_steps(board) -> list[dict]:
    """The steps of a `BoardState` as plain JSON: ``{name, status, detail}`` for each, and for the
    ones that started also ``started_at`` (ISO, UTC), ``finished_at`` (done or failed), ``done``,
    ``total``, ``sites`` (postings per board or feed), ``hosts`` in flight, ``phase``, ``items`` (the
    boards or sources it reads: ``{id, name, state}``, a running board also its ``activity``) and, for discover, ``request`` / ``requests``. The board must have been folded on the wall clock."""
    out = []
    for view in board.steps.values():
        item: dict = {"name": view.name, "status": view.status, "detail": view.detail}
        if view.status in ("running", "done", "failed"):
            item["started_at"] = _iso(view.started)
            if view.status != "running":
                item["finished_at"] = _iso(view.started + view.elapsed)
            item["done"] = view.done
            if view.total is not None:
                item["total"] = view.total
            if view.postings:
                item["sites"] = dict(view.postings)
            item["hosts"] = list(view.hosts)
            if view.phase:
                item["phase"] = view.phase
            if view.items:
                item["items"] = [{"id": i.id, "name": i.label, "state": i.state, **({"activity": dict(i.activity)} if i.activity else {})}
                                 for i in view.items]
            if view.request:
                item["request"] = view.request
            if view.requests:
                item["requests"] = list(view.requests)
        out.append(item)
    return out


def read_progress(jobs_dir: Path) -> dict | None:
    """The latest snapshot in `jobs_dir/.progress.json`, or None if missing or unreadable."""
    try:
        data = json.loads((Path(jobs_dir) / PROGRESS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def format_elapsed(seconds: float) -> str:
    """"3m20s" for 200 seconds."""
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s"


@contextmanager
def heartbeat(label: str, *, stage: str, interval_s: float = 30.0, clock=time.monotonic):
    """Report "<label> · 3m20s elapsed" every `interval_s` while the block runs.

    For opaque long steps (the tailor run): the events keep the CLI line and
    the MCP client's idle timeout alive. Nothing is emitted if the block ends
    sooner than `interval_s`.
    """
    stop = threading.Event()
    started = clock()

    def _beat():
        while not stop.wait(interval_s):
            report(f"{label} · {format_elapsed(clock() - started)} elapsed", stage=stage)

    thread = threading.Thread(target=_beat, name="progress-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
