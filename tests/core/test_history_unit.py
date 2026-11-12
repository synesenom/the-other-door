"""Unit tests for history.py — pure offline, no network.

Tests cover:
- is_new() for unknown, recorded, stale, and fresh entries
- record() sets first_seen / does not overwrite it
- touch() updates last_seen
- save() / load round-trip and atomicity
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


from door.core.history import HistoryStore


_NOW = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)
_OLD = _NOW - timedelta(days=5)
_RECENT = _NOW - timedelta(hours=1)


def _store(tmp_path: Path, *, entries: dict | None = None) -> HistoryStore:
    """Build a HistoryStore backed by a tmp file, optionally pre-populated."""
    path = tmp_path / "history.json"
    if entries is not None:
        path.write_text(json.dumps(entries))
    return HistoryStore(path)


# --------------------------------------------------------------------------- #
# is_new — unknown platform_id
# --------------------------------------------------------------------------- #

def test_is_new_unknown_platform_id(tmp_path):
    store = _store(tmp_path)
    assert store.is_new("site.pid-999", "jobindex", recheck_after_days=None) is True


def test_is_new_none_platform_id_always_true(tmp_path):
    """platform_id=None postings are always treated as new."""
    store = _store(tmp_path)
    assert store.is_new(None, "jobindex", recheck_after_days=None) is True


# --------------------------------------------------------------------------- #
# is_new — after record()
# --------------------------------------------------------------------------- #

def test_is_new_after_record_returns_false(tmp_path):
    store = _store(tmp_path)
    store.record("site.pid-1", "pid-1", "https://x/1", "jobindex", now=_NOW)
    assert store.is_new("site.pid-1", "jobindex", recheck_after_days=None) is False


# --------------------------------------------------------------------------- #
# is_new — recheck_after_days
# --------------------------------------------------------------------------- #

def test_recheck_stale_entry_returns_true(tmp_path):
    """Entry with last_seen 5 days ago and recheck_after_days=3 → is_new() True."""
    entries = {
        "site.pid-old": {
            "job_id": "j1", "url": "u", "source": "jobindex",
            "first_seen": _OLD.isoformat(), "last_seen": _OLD.isoformat(),
            "status": "seen",
        }
    }
    store = _store(tmp_path, entries=entries)
    assert store.is_new("site.pid-old", "jobindex", recheck_after_days=3, now=_NOW) is True


def test_is_new_fresh_entry_within_recheck_window_is_false(tmp_path):
    """Entry seen 1 hour ago and recheck_after_days=1 → is_new() False."""
    entries = {
        "site.pid-fresh": {
            "job_id": "j2", "url": "u", "source": "jobindex",
            "first_seen": _RECENT.isoformat(), "last_seen": _RECENT.isoformat(),
            "status": "seen",
        }
    }
    store = _store(tmp_path, entries=entries)
    assert store.is_new("site.pid-fresh", "jobindex", recheck_after_days=1, now=_NOW) is False


def test_recheck_after_days_none_never_resurfaces(tmp_path):
    """recheck_after_days=None means never re-surface, even very old entries."""
    entries = {
        "site.pid-ancient": {
            "job_id": "j3", "url": "u", "source": "jobindex",
            "first_seen": _OLD.isoformat(), "last_seen": _OLD.isoformat(),
            "status": "seen",
        }
    }
    store = _store(tmp_path, entries=entries)
    assert store.is_new("site.pid-ancient", "jobindex", recheck_after_days=None, now=_NOW) is False


# --------------------------------------------------------------------------- #
# record()
# --------------------------------------------------------------------------- #

def test_record_sets_first_seen_and_last_seen(tmp_path):
    store = _store(tmp_path)
    store.record("site.pid-x", "pid-x", "https://x/1", "jobindex", now=_NOW)
    entry = store._data["site.pid-x"]
    assert entry["first_seen"] == _NOW.isoformat()
    assert entry["last_seen"] == _NOW.isoformat()
    assert entry["status"] == "seen"
    assert entry["source"] == "jobindex"
    assert entry["job_id"] == "site.pid-x"
    assert entry["platform_id"] == "pid-x"
    assert entry["url"] == "https://x/1"


def test_record_does_not_overwrite_first_seen(tmp_path):
    """Calling record() twice must preserve the original first_seen."""
    store = _store(tmp_path)
    store.record("site.pid-x", "pid-x", "https://x/1", "jobindex", now=_OLD)
    store.record("site.pid-x", "pid-x", "https://x/1", "jobindex", now=_NOW)
    assert store._data["site.pid-x"]["first_seen"] == _OLD.isoformat()
    assert store._data["site.pid-x"]["last_seen"] == _NOW.isoformat()


# --------------------------------------------------------------------------- #
# touch()
# --------------------------------------------------------------------------- #

def test_touch_updates_last_seen(tmp_path):
    store = _store(tmp_path)
    store.record("site.pid-y", "pid-y", "https://y/1", "jobindex", now=_OLD)
    store.touch("site.pid-y", now=_NOW)
    assert store._data["site.pid-y"]["last_seen"] == _NOW.isoformat()
    # first_seen must not change
    assert store._data["site.pid-y"]["first_seen"] == _OLD.isoformat()


def test_touch_unknown_pid_is_noop(tmp_path):
    """touch() on an unknown pid must not raise."""
    store = _store(tmp_path)
    store.touch("site.pid-nonexistent", now=_NOW)  # should not raise


# --------------------------------------------------------------------------- #
# save() / load round-trip
# --------------------------------------------------------------------------- #

def test_save_load_round_trip(tmp_path):
    path = tmp_path / "history.json"
    store = HistoryStore(path)
    store.record("site.pid-1", "pid-1", "https://a/1", "jobindex", now=_NOW)
    store.record("site.pid-2", "pid-2", "https://b/2", "thehub", now=_OLD)
    store.save()

    # New instance, load from disk
    store2 = HistoryStore(path)
    assert "site.pid-1" in store2._data
    assert "site.pid-2" in store2._data
    assert store2._data["site.pid-1"]["source"] == "jobindex"
    assert store2._data["site.pid-2"]["first_seen"] == _OLD.isoformat()


def test_save_is_atomic_tmp_not_left_behind(tmp_path):
    path = tmp_path / "history.json"
    store = HistoryStore(path)
    store.record("site.pid-1", "pid-1", "https://a/1", "jobindex", now=_NOW)
    store.save()

    assert list(tmp_path.iterdir()) == [path], "no temp file should be left after an atomic save"


def test_load_corrupt_file_falls_back_to_empty(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("NOT VALID JSON {{{{")
    store = HistoryStore(path)
    # Should start with empty data, not crash
    assert store._data == {}


def test_load_missing_file_starts_empty(tmp_path):
    path = tmp_path / "nonexistent_history.json"
    store = HistoryStore(path)
    assert store._data == {}


# --------------------------------------------------------------------------- #
# known_ids() — issue #134: the set of platform_ids "already seen enough" to
# skip an expensive detail fetch for, for a given source.
# --------------------------------------------------------------------------- #

def test_known_ids_includes_entry_within_recheck_window(tmp_path):
    entries = {
        "jobindex.pid-fresh": {
            "job_id": "j1", "url": "u", "source": "jobindex",
            "first_seen": _RECENT.isoformat(), "last_seen": _RECENT.isoformat(),
            "status": "seen",
        }
    }
    store = _store(tmp_path, entries=entries)
    assert store.known_ids("jobindex", recheck_after_days=7, now=_NOW) == {"pid-fresh"}


def test_known_ids_excludes_entry_past_recheck_window(tmp_path):
    """An entry older than recheck_after_days re-surfaces as 'new' -> excluded."""
    entries = {
        "jobindex.pid-old": {
            "job_id": "j1", "url": "u", "source": "jobindex",
            "first_seen": _OLD.isoformat(), "last_seen": _OLD.isoformat(),
            "status": "seen",
        }
    }
    store = _store(tmp_path, entries=entries)
    assert store.known_ids("jobindex", recheck_after_days=3, now=_NOW) == set()


def test_known_ids_excludes_entries_from_a_different_source(tmp_path):
    entries = {
        "jobindex.pid-jobindex": {
            "job_id": "j1", "url": "u", "source": "jobindex",
            "first_seen": _RECENT.isoformat(), "last_seen": _RECENT.isoformat(),
            "status": "seen",
        },
        "thehub.pid-thehub": {
            "job_id": "j2", "url": "u", "source": "thehub",
            "first_seen": _RECENT.isoformat(), "last_seen": _RECENT.isoformat(),
            "status": "seen",
        },
    }
    store = _store(tmp_path, entries=entries)
    assert store.known_ids("jobindex", recheck_after_days=None, now=_NOW) == {"pid-jobindex"}


# --------------------------------------------------------------------------- #
# job-id keys (#313)
# --------------------------------------------------------------------------- #

def test_same_platform_id_from_two_sites_are_both_new(tmp_path):
    store = _store(tmp_path)
    store.record("jobindex.1", "1", "https://a/1", "jobindex", now=_NOW)
    assert store.is_new("jobindex.1", "jobindex", recheck_after_days=None) is False
    assert store.is_new("greenhouse.1", "greenhouse", recheck_after_days=None) is True


def test_record_keys_the_file_by_job_id_and_stores_the_platform_id(tmp_path):
    store = _store(tmp_path)
    store.record("jobindex.h1", "h1", "https://a/1", "jobindex", now=_NOW)
    store.save()
    data = json.loads((tmp_path / "history.json").read_text())
    assert list(data) == ["jobindex.h1"]
    assert data["jobindex.h1"]["platform_id"] == "h1"


def test_known_ids_returns_platform_ids_of_that_source_only(tmp_path):
    store = _store(tmp_path)
    store.record("jobindex.h1", "h1", "u", "jobindex", now=_NOW)
    store.record("greenhouse.h1", "h1", "u", "greenhouse", now=_NOW)
    store.record("greenhouse.g2", "g2", "u", "greenhouse", now=_NOW)
    assert store.known_ids("jobindex", None, now=_NOW) == {"h1"}
    assert store.known_ids("greenhouse", None, now=_NOW) == {"h1", "g2"}


def test_known_ids_strips_the_source_prefix_for_a_legacy_entry(tmp_path):
    entries = {"jobindex.h9": {"job_id": "jobindex.h9", "url": "u", "source": "jobindex",
                               "first_seen": _RECENT.isoformat(), "last_seen": _RECENT.isoformat(), "status": "seen"}}
    store = _store(tmp_path, entries=entries)
    assert store.known_ids("jobindex", None, now=_NOW) == {"h9"}
