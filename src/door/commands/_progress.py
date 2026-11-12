"""One terminal line per step: a yellow spinner while it runs, then a green ✓ or a red ✗.

The spinner only draws on a terminal; anywhere else (a pipe, a log, tests)
only the final line is printed, and click drops the colours. `LiveLine` is the
same idea for the long commands: it renders the progress events of
`door.core.progress` (a line per scraped site, a `scored n/total` counter).
"""

import itertools
import shutil
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager

import click

_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
CHECK = click.style("✓", fg="green")
CROSS = click.style("✗", fg="red")


def step(label: str, work: Callable[[], tuple[bool, str | None]]) -> bool:
    """Run ``work`` (returns ``(ok, error)``) under a spinner labelled ``label``; print the outcome."""
    done = threading.Event()
    spinner = None
    if sys.stdout.isatty():
        def spin():
            for frame in itertools.cycle(_FRAMES):
                if done.is_set():
                    return
                sys.stdout.write(f"\r  {click.style(frame, fg='yellow')} {label}")
                sys.stdout.flush()
                time.sleep(0.1)

        spinner = threading.Thread(target=spin, daemon=True)
        spinner.start()
    try:
        ok, error = work()
    finally:
        done.set()
        if spinner is not None:
            spinner.join()
            sys.stdout.write("\r\033[K")
    click.echo(f"  {CHECK if ok else CROSS} {label}")
    if not ok and error:
        click.echo(f"      {error}", err=True)
    return ok


_WARN = click.style("⚠", fg="yellow")
_OUTCOME_GLYPHS = {"ok": CHECK, "empty": _WARN}


class LiveLine:
    """Draws progress events on one terminal line (issue #202).

    A `door.core.progress.Reporter`: pass it as a core's ``progress=``. The
    latest event is shown after a yellow spinner (``jobindex: 'x': 3 results``,
    ``scored 3/12``); an event that closes a step (it has an ``outcome``: a
    scraped site, one of `add`'s steps) clears the line and leaves a permanent
    ``✓ <message>`` line behind (``✗`` for failures, ``⚠`` for an empty site). ``stop()`` clears
    the spinner line.

    Args:
        stream: Where to draw (default: ``sys.stdout`` at construction).
        animate: Spin from a background thread (default: whether ``stream`` is
            a terminal). Without it each event redraws synchronously, which is
            what tests use.
        interval: Seconds between spinner frames.
    """

    def __init__(self, stream=None, *, animate: bool | None = None, interval: float = 0.1):
        self._stream = stream if stream is not None else sys.stdout
        isatty = getattr(self._stream, "isatty", lambda: False)
        self._color = bool(isatty())  # no ANSI colours into a pipe or a captured stream
        self._animate = self._color if animate is None else animate
        self._interval = interval
        self._lock = threading.Lock()
        self._frames = itertools.cycle(_FRAMES)
        self._text: str | None = None
        self._drawn = False
        # Sites whose outcome line this renderer printed, so the summary can skip them.
        self.finished_sites: set[str] = set()
        self._stop = threading.Event()
        self._thread = None
        if self._animate:
            self._thread = threading.Thread(target=self._spin, name="live-progress", daemon=True)
            self._thread.start()

    # -- Reporter -------------------------------------------------------------
    def report(self, event) -> None:
        with self._lock:
            if event.outcome:
                self._clear()
                glyph = _OUTCOME_GLYPHS.get(event.outcome, CROSS)
                if not self._color:
                    glyph = click.unstyle(glyph)
                self._write(f"  {glyph} {event.message}\n")
                if event.site:
                    self.finished_sites.add(event.site)
                self._text = None
                return
            self._text = event.line
            if not self._animate:
                self._draw()

    def stop(self) -> None:
        """Stop the spinner and clear its line."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        with self._lock:
            self._clear()
            self._text = None

    # -- drawing (call with the lock held) ------------------------------------
    def _write(self, text: str) -> None:
        try:
            self._stream.write(text)
            self._stream.flush()
        except (ValueError, OSError):  # a closed or broken terminal must not stop a scrape
            pass

    def _draw(self) -> None:
        if self._text is None:
            return
        width = shutil.get_terminal_size((80, 24)).columns - 6
        text = self._text if len(self._text) <= width else self._text[: max(width - 1, 1)] + "…"
        frame = next(self._frames)
        if self._color:
            frame = click.style(frame, fg="yellow")
        self._write(f"\r  {frame} {text}\033[K")
        self._drawn = True

    def _clear(self) -> None:
        if self._drawn:
            self._write("\r\033[K")
            self._drawn = False

    def _spin(self) -> None:
        while not self._stop.wait(self._interval):
            with self._lock:
                self._draw()


@contextmanager
def live_progress(enabled: bool, *, animate: bool | None = None, stream=None):
    """Yield a started `LiveLine` (to pass as ``progress=``) or None when ``enabled`` is false.

    Always stops and clears the line on exit.
    """
    if not enabled:
        yield None
        return
    live = LiveLine(stream, animate=animate)
    try:
        yield live
    finally:
        live.stop()
