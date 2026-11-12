"""A lock around the `jobs/` ledgers (issue #145).

A `find` in one terminal and a review conversation in another can write
`history.json`, `applications.json` and `last_review.json` at the same time
(marking a job applied while a run scrapes, or a discard mid-run). The
atomic tmp+rename writes prevent a corrupt file but not a lost update, so
every core that writes a ledger does it under `ledger_lock`, and `find` holds
it for the whole run.

The lock never blocks: a second writer gets `LockHeldError` at once, whose
message says who holds it ("a run is in progress (started 06:30, pid 4242)"),
so a conversation gets a clear answer instead of a hung tool call.

Mechanics: an OS advisory lock on `jobs/.lock` (`fcntl.flock` on POSIX,
`msvcrt.locking` on Windows), which the OS drops when the holder dies — so a
crashed run never leaves a lock behind; a leftover `jobs/.lock.json` naming a
dead pid is simply overwritten. The holder's pid, purpose and start time go
in the side file `jobs/.lock.json` (on Windows a locked byte range cannot be
read by other processes, so it cannot live in the lock file itself). The lock
is re-entrant within one thread: a core that holds it can call another
core that takes it again. A different thread of the same process
(the MCP server runs tools in worker threads) is refused like another process.

While held, the lock also attaches a `ProgressFile` sink (issue #202), so
`jobs/.progress.json` mirrors the latest progress event; it is removed with
the lock, and `status_summary` reads it to answer "how far is it?".
"""

from __future__ import annotations

import json
import os
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from door.core import progress, workspace

_LOCK_NAME = ".lock"
_INFO_NAME = ".lock.json"

# Locks this process holds: resolved jobs_dir -> [file object, depth, info,
# holder thread id, progress sink].
_held: dict[str, list] = {}
_held_guard = threading.Lock()


class LockHeldError(RuntimeError):
    """Another process holds the `jobs/` ledger lock."""


class SyncConflict(RuntimeError):
    """Google Drive and this computer both changed (issue #265); the one sync failure that refuses a command."""


# Google Drive sync (issue #265). The outermost block pulls once the OS lock is held and
# pushes just before it is released, for every purpose but the sync ones themselves (which
# would recurse). Both run outside `_held_guard`; the defaults import `sync` lazily
# (`sync` imports the archive commands, which import this module). Tests swap them.
_NO_SYNC_PURPOSES = frozenset({"export", "import", "sync"})


def _default_pre(purpose: str, jobs_dir: Path) -> None:
    from door.core import sync

    sync.on_acquire(purpose, jobs_dir)


def _default_post(purpose: str, jobs_dir: Path) -> None:
    from door.core import sync

    sync.on_release(purpose, jobs_dir)


pre_acquire_hook = _default_pre
post_release_hook = _default_post


def _run_hook(hook, purpose: str, jobs_dir: Path, *, refuse_on_conflict: bool) -> None:
    """Call a sync hook; its failures never reach the command, except a `SyncConflict` from the pre-hook."""
    try:
        hook(purpose, jobs_dir)
    except SyncConflict:
        if refuse_on_conflict:
            raise
        progress.report("Drive sync skipped: both sides changed; run `./door data sync`")
    except Exception as exc:  # noqa: BLE001 - sync must never fail a command
        progress.report(f"Drive sync skipped: {exc}")


def _key(jobs_dir: Path) -> str:
    return str(Path(jobs_dir).resolve())


def _held_depth(jobs_dir: Path) -> int:
    """How many nested `ledger_lock` blocks this process has open on `jobs_dir`."""
    entry = _held.get(_key(jobs_dir))
    if not entry or entry[3] != threading.get_ident():
        return 0
    return entry[1]


def _try_os_lock(fh) -> bool:
    """Take a non-blocking exclusive lock on `fh`; False if someone else has it."""
    if sys.platform == "win32":
        import msvcrt

        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    import fcntl

    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _os_unlock(fh) -> None:
    if sys.platform == "win32":
        import msvcrt

        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return

    import fcntl

    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _read_info(jobs_dir: Path) -> dict:
    try:
        return json.loads((Path(jobs_dir) / _INFO_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _describe(info: dict) -> str:
    """"a run is in progress (started 06:30, pid 4242)" or the generic form."""
    details = []
    started = info.get("started_at")
    if started:
        try:
            details.append(f"started {datetime.fromisoformat(started).astimezone().strftime('%H:%M')}")
        except ValueError:
            details.append(f"started {started}")
    if info.get("pid") is not None:
        details.append(f"pid {info['pid']}")
    suffix = f" ({', '.join(details)})" if details else ""
    purpose = info.get("purpose")
    if purpose == "run":
        return f"a run is in progress{suffix}; try again when it has finished"
    what = f" ({purpose})" if purpose else ""
    return f"another process of The other door is writing the ledgers{what}{suffix}; try again in a moment"


def lock_holder(jobs_dir: Path) -> dict | None:
    """Who holds the lock right now — ``{"pid", "purpose", "started_at"}`` — or None.

    Probes without keeping the lock. A `.lock.json` left by a dead process
    does not count: only a live OS lock does.
    """
    jobs_dir = Path(jobs_dir)
    entry = _held.get(_key(jobs_dir))
    if entry is not None:
        return dict(entry[2])
    lock_path = jobs_dir / _LOCK_NAME
    if not lock_path.exists():
        return None
    with open(lock_path, "a+") as fh:
        if _try_os_lock(fh):
            _os_unlock(fh)
            return None
    return _read_info(jobs_dir) or {"pid": None, "purpose": None, "started_at": None}


@contextmanager
def ledger_lock(jobs_dir: Path, purpose: str):
    """Hold the `jobs_dir` ledger lock for the block, or raise `LockHeldError` at once.

    Args:
        jobs_dir: The `jobs/` directory (created if missing).
        purpose: What the holder is doing ("run", "set_status", "discard", ...),
            shown to anyone refused while it is held.
    """
    jobs_dir = Path(jobs_dir)
    key = _key(jobs_dir)

    with _held_guard:
        entry = _held.get(key)
        if entry is not None:
            if entry[3] != threading.get_ident():
                raise LockHeldError(_describe(entry[2]))
            entry[1] += 1
            nested = True
        else:
            nested = False
            jobs_dir.mkdir(parents=True, exist_ok=True)
            fh = open(jobs_dir / _LOCK_NAME, "a+")
            if not _try_os_lock(fh):
                fh.close()
                raise LockHeldError(_describe(_read_info(jobs_dir)))
            info = {
                "pid": os.getpid(),
                "purpose": purpose,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                (jobs_dir / _INFO_NAME).write_text(json.dumps(info), encoding="utf-8")
            except BaseException:
                _os_unlock(fh)
                fh.close()
                raise
            (jobs_dir / progress.PROGRESS_NAME).unlink(missing_ok=True)
            sink = progress.ProgressFile(jobs_dir / progress.PROGRESS_NAME)
            progress.register(sink)
            _held[key] = [fh, 1, info, threading.get_ident(), sink]

    sync_here = not nested and purpose not in _NO_SYNC_PURPOSES
    pulled = False
    try:
        if sync_here:
            _run_hook(pre_acquire_hook, purpose, jobs_dir, refuse_on_conflict=True)
            pulled = True
        if not nested:
            workspace.move_day_folders(jobs_dir)  # what an older version (or an old archive) left
        yield
    finally:
        if sync_here and pulled:
            _run_hook(post_release_hook, purpose, jobs_dir, refuse_on_conflict=False)
        with _held_guard:
            entry = _held[key]
            entry[1] -= 1
            if entry[1] == 0 and not nested:
                del _held[key]
                progress.unregister(entry[4])
                entry[4].close()
                try:
                    (jobs_dir / progress.PROGRESS_NAME).unlink(missing_ok=True)
                except OSError:
                    pass
                try:
                    (jobs_dir / _INFO_NAME).unlink(missing_ok=True)
                except OSError:
                    pass
                _os_unlock(entry[0])
                entry[0].close()
