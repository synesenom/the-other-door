"""Unit tests for the jobs/ ledger lock (issue #145, scope addition).

A `find` and an interactive review session on the same machine can
write `history.json` / `applications.json` / `last_review.json` at the same
time. `door.core.lock.ledger_lock` makes the second writer fail fast with a
clear message instead of silently losing an update.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from door.core import lock as lock_mod
from door.core.lock import LockHeldError, ledger_lock, lock_holder
from paths import SRC_DIR


def _spawn_holder(jobs_dir: Path, purpose: str = "run") -> subprocess.Popen:
    """A second process that takes the lock, says so, and holds it until stdin closes."""
    code = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(SRC_DIR)!r})
        from pathlib import Path
        from door.core.lock import ledger_lock
        with ledger_lock(Path({str(jobs_dir)!r}), {purpose!r}):
            print("held", flush=True)
            sys.stdin.read()
        """
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout.readline().strip() == "held"
    return proc


def _release(proc: subprocess.Popen) -> None:
    proc.stdin.close()
    proc.wait(timeout=10)


def test_lock_creates_jobs_dir(tmp_path):
    jobs_dir = tmp_path / "jobs"
    with ledger_lock(jobs_dir, "run"):
        assert jobs_dir.is_dir()


def test_lock_is_reentrant_within_one_process(tmp_path):
    """`run --and-prepare` holds the lock and calls `_prepare_core`, which takes it again."""
    with ledger_lock(tmp_path, "run"):
        with ledger_lock(tmp_path, "prepare"):
            pass
        # Still held by the outer block after the inner one exits.
        assert lock_mod._held_depth(tmp_path) == 1
    assert lock_mod._held_depth(tmp_path) == 0


def test_second_process_is_refused_with_a_run_in_progress_message(tmp_path):
    proc = _spawn_holder(tmp_path, "run")
    try:
        with pytest.raises(LockHeldError) as exc_info:
            with ledger_lock(tmp_path, "set_status"):
                pass
        message = str(exc_info.value)
        assert "a run is in progress" in message
        assert f"pid {proc.pid}" in message
    finally:
        _release(proc)

    # Once the holder exits the lock is free again.
    with ledger_lock(tmp_path, "set_status"):
        pass


def test_non_run_holder_gets_a_generic_message(tmp_path):
    proc = _spawn_holder(tmp_path, "discard")
    try:
        with pytest.raises(LockHeldError, match="discard"):
            with ledger_lock(tmp_path, "set_status"):
                pass
    finally:
        _release(proc)


def test_lock_holder_reports_the_live_holder(tmp_path):
    assert lock_holder(tmp_path) is None
    proc = _spawn_holder(tmp_path, "run")
    try:
        holder = lock_holder(tmp_path)
        assert holder["pid"] == proc.pid
        assert holder["purpose"] == "run"
    finally:
        _release(proc)
    assert lock_holder(tmp_path) is None


def test_stale_lock_info_from_a_dead_process_is_taken_over(tmp_path):
    """A leftover lock file from a crashed run (pid no longer alive) does not block."""
    (tmp_path / ".lock").write_text("")
    (tmp_path / ".lock.json").write_text(
        json.dumps({"pid": 999_999_999, "purpose": "run", "started_at": "2026-01-01T06:30:00+00:00"})
    )
    assert lock_holder(tmp_path) is None
    with ledger_lock(tmp_path, "set_status"):
        assert lock_holder(tmp_path)["purpose"] == "set_status"


def test_a_failed_info_write_releases_the_lock(tmp_path, monkeypatch):
    real_write = Path.write_text

    def failing_write(self, *args, **kwargs):
        if self.name == ".lock.json":
            raise OSError("disk full")
        return real_write(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_write)
    with pytest.raises(OSError, match="disk full"):
        with ledger_lock(tmp_path, "run"):
            pass
    monkeypatch.setattr(Path, "write_text", real_write)
    assert lock_mod._held_depth(tmp_path) == 0
    with ledger_lock(tmp_path, "set_status"):
        pass


# --- thread awareness and the progress sink (issue #202) ------------------------


def _in_thread(fn):
    """Run `fn` in a second thread; return (result, exception)."""
    import threading

    box = {}

    def _run():
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc

    t = threading.Thread(target=_run)
    t.start()
    t.join()
    return box.get("result"), box.get("exc")


def test_other_thread_in_same_process_gets_lock_held_error(tmp_path):
    def attempt():
        with ledger_lock(tmp_path, "set_status"):
            return "got it"

    with ledger_lock(tmp_path, "run"):
        result, exc = _in_thread(attempt)
    assert result is None
    assert isinstance(exc, LockHeldError)
    assert "a run is in progress" in str(exc)
    assert lock_mod._held_depth(tmp_path) == 0


def test_same_thread_nested_acquire_still_reentrant(tmp_path):
    with ledger_lock(tmp_path, "run"):
        with ledger_lock(tmp_path, "prepare"):
            assert lock_mod._held_depth(tmp_path) == 2
        assert lock_mod._held_depth(tmp_path) == 1


def test_held_depth_is_zero_from_another_thread(tmp_path):
    with ledger_lock(tmp_path, "run"):
        depth, _ = _in_thread(lambda: lock_mod._held_depth(tmp_path))
    assert depth == 0


def test_lock_holder_still_reports_holder_to_other_thread(tmp_path):
    with ledger_lock(tmp_path, "run"):
        holder, _ = _in_thread(lambda: lock_holder(tmp_path))
    assert holder["purpose"] == "run"


def test_progress_json_written_while_held_and_removed_on_outermost_release(tmp_path):
    from door.core import progress

    path = tmp_path / ".progress.json"
    with ledger_lock(tmp_path, "run"):
        progress.report("m", 1, 2)
        assert json.loads(path.read_text())["message"] == "m"
        with ledger_lock(tmp_path, "inner"):
            progress.report("n", 2, 2)
        assert path.exists()
    assert not path.exists()


def test_stale_progress_json_removed_on_acquire(tmp_path):
    (tmp_path / ".progress.json").write_text('{"message": "stale"}')
    with ledger_lock(tmp_path, "run"):
        assert not (tmp_path / ".progress.json").exists()


def test_progress_sink_detached_after_release(tmp_path):
    from door.core import progress

    with ledger_lock(tmp_path, "run"):
        pass
    progress.report("late")
    assert not (tmp_path / ".progress.json").exists()


# --------------------------------------------------------------------------- Drive sync hooks (#265)
@pytest.fixture
def hooks(monkeypatch):
    """Record every pre/post hook call instead of syncing."""
    calls = []
    monkeypatch.setattr(lock_mod, "pre_acquire_hook", lambda purpose, jobs_dir: calls.append(("pre", purpose)))
    monkeypatch.setattr(lock_mod, "post_release_hook", lambda purpose, jobs_dir: calls.append(("post", purpose)))
    return calls


def test_hooks_run_once_around_the_outermost_block(tmp_path, hooks):
    with ledger_lock(tmp_path, "run"):
        assert hooks == [("pre", "run")]
        with ledger_lock(tmp_path, "prepare"):
            pass
        assert hooks == [("pre", "run")]
    assert hooks == [("pre", "run"), ("post", "run")]


@pytest.mark.parametrize("purpose", ["export", "import", "sync"])
def test_no_hooks_for_the_sync_purposes(tmp_path, hooks, purpose):
    with ledger_lock(tmp_path, purpose):
        pass
    assert hooks == []


def test_post_hook_runs_while_the_os_lock_is_still_held(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(lock_mod, "pre_acquire_hook", lambda *a: None)
    monkeypatch.setattr(lock_mod, "post_release_hook", lambda *a: seen.append(lock_holder(tmp_path)))
    with ledger_lock(tmp_path, "run"):
        pass
    assert seen[0]["purpose"] == "run"
    assert lock_holder(tmp_path) is None


def test_hook_errors_are_swallowed_and_the_lock_released(tmp_path, monkeypatch):
    def boom(*a):
        raise RuntimeError("drive exploded")

    monkeypatch.setattr(lock_mod, "pre_acquire_hook", boom)
    monkeypatch.setattr(lock_mod, "post_release_hook", boom)
    ran = []
    with ledger_lock(tmp_path, "run"):
        ran.append(True)
    assert ran == [True]
    assert lock_holder(tmp_path) is None


def test_hooks_are_not_called_under_the_guard(tmp_path, monkeypatch):
    def pre(purpose, jobs_dir):
        with ledger_lock(jobs_dir, "inner"):  # re-enters: needs the guard free
            pass

    monkeypatch.setattr(lock_mod, "pre_acquire_hook", pre)
    monkeypatch.setattr(lock_mod, "post_release_hook", lambda *a: None)
    with ledger_lock(tmp_path, "run"):
        pass
    assert lock_holder(tmp_path) is None


def test_a_conflict_in_the_pre_hook_refuses_the_block_and_releases(tmp_path, monkeypatch):
    def pre(*a):
        raise lock_mod.SyncConflict("both sides changed")

    post = []
    monkeypatch.setattr(lock_mod, "pre_acquire_hook", pre)
    monkeypatch.setattr(lock_mod, "post_release_hook", lambda *a: post.append(1))
    ran = []
    with pytest.raises(lock_mod.SyncConflict, match="both sides"):
        with ledger_lock(tmp_path, "run"):
            ran.append(True)
    assert ran == [] and post == []
    assert lock_holder(tmp_path) is None


def test_a_refused_second_holder_runs_no_hooks(tmp_path, hooks):
    proc = _spawn_holder(tmp_path)
    try:
        with pytest.raises(LockHeldError):
            with ledger_lock(tmp_path, "set_status"):
                pass
    finally:
        _release(proc)
    assert hooks == []
