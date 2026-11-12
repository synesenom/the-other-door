"""The problem log (#593): `<data folder>/logs/door.log`, one line per thing that went wrong.

The app shows an error only when it prevents a mistake or the user can fix it (docs/design/README.md,
principle 8); the rest goes here, for `data report` to pack and the user to send. The MCP server and
the CLI call `setup` once when they start (`mcp_server.main`, `door/__main__.py`); until then, as in
the tests, nothing is written anywhere. The desktop app's main process appends to the same file
(`app/src/main/problem-log.ts`).

What goes in: a tool call that failed or answered ``{"error"}`` (its name and the message, never its
arguments), a warning a tool returned, a crash, and from each run record the sites that failed or
came back empty and the ads left unscored (by id). No CV text, profile values or ad text: a line names
a tool, a site or a job id, and the message. Each line is ``<UTC time> <LEVEL> <where>: <message>``,
on one line and bounded. The file rotates at `MAX_BYTES`, keeping `BACKUPS` older ones.
"""

from __future__ import annotations

import logging
import logging.handlers
import time
import traceback
from pathlib import Path

from door.core import runs, workspace

FOLDER = "logs"
FILE = "door.log"
MAX_BYTES = 1_000_000
BACKUPS = 2  # door.log, door.log.1, door.log.2: about 3 MB at most
_MAX_MESSAGE = 500
_FRAMES = 4  # a crash names where it happened: the innermost frames

_logger = logging.getLogger("door")
_logger.addHandler(logging.NullHandler())  # no handler set up: nothing written, not even to stderr
_logger.propagate = False
_logger.setLevel(logging.INFO)
_handler: logging.Handler | None = None


class _Handler(logging.handlers.RotatingFileHandler):
    """Opens the file, and makes `logs/`, at the first line: a run where nothing goes wrong leaves nothing."""

    def _open(self):
        Path(self.baseFilename).parent.mkdir(exist_ok=True)
        return super()._open()


def setup(home: Path | str | None = None) -> Path | None:
    """Write the log under ``home/logs/`` (default `workspace.HOME`) from now on; a second call moves it.

    Returns:
        The log file (made, with `logs/`, at its first line), or None when the data folder does not
        exist (nothing is created).
    """
    global _handler
    close()
    folder = Path(home) if home is not None else workspace.HOME
    if not folder.is_dir():
        return None
    path = folder / FOLDER / FILE
    handler = _Handler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8", delay=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%SZ")
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    _logger.addHandler(handler)
    _handler = handler
    return path


def close() -> None:
    """Stop writing the log (tests; `setup` again)."""
    global _handler
    if _handler is not None:
        _logger.removeHandler(_handler)
        _handler.close()
        _handler = None


def _one_line(text: object) -> str:
    line = " ".join(str(text).split())
    return line if len(line) <= _MAX_MESSAGE else line[: _MAX_MESSAGE - 1] + "…"


def failure(where: str, message: object) -> None:
    """``ERROR <where>: <message>``; *where* is e.g. ``tool show`` or ``site thehub failed``."""
    _logger.error("%s: %s", where, _one_line(message))


def warning(where: str, message: object) -> None:
    _logger.warning("%s: %s", where, _one_line(message))


def crash(where: str, exc: BaseException) -> None:
    """An exception nobody expected, with the innermost frames it went through, on one line."""
    frames = traceback.extract_tb(exc.__traceback__)[-_FRAMES:]
    at = " > ".join(f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in frames)
    _logger.error("%s: %s: %s%s", where, type(exc).__name__, _one_line(exc), f" (at {at})" if at else "")


def run_record(record: dict) -> None:
    """A `find` run's sites that failed (``failed``, ``error``) or came back ``empty``, and its unscored ads."""
    for entry in runs.site_entries(record):
        outcome = entry.get("outcome")
        if outcome not in ("failed", "error", "empty"):
            continue
        said = [*(entry.get("errors") or []), entry.get("error"), entry.get("warning")]
        message = next((m for m in said if m), "no message")
        (warning if outcome == "empty" else failure)(f"site {entry.get('site')} {outcome}", message)
    for unscored in (record.get("match") or {}).get("failures") or []:
        failure(f"unscored {unscored.get('id')}", unscored.get("error") or "no score")
