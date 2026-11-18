"""User state is written atomically: a write that fails part-way leaves the old file whole (#363)."""

import json
import os

import pytest

from door.commands import _common
from door.core import models, recurring


@pytest.fixture
def failing_swap(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)


def test_save_posting_keeps_old_file(tmp_path, failing_swap):
    path = tmp_path / "p.json"
    path.write_text('{"old": true}', encoding="utf-8")
    posting = models.JobPosting(
        id="x.1", title="t", company="c", location="l", url="https://e.x/1", description="d", source="x", scraped_at="2026-01-01T00:00:00"
    )
    with pytest.raises(OSError):
        models.save_posting(posting, path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
    assert [p.name for p in tmp_path.iterdir()] == ["p.json"]


def test_cv_write_keeps_old_file(tmp_path, failing_swap):
    path = tmp_path / "cv.md"
    path.write_text("old cv", encoding="utf-8")
    with pytest.raises(OSError):
        _common._write_with_backup(path, "new cv")
    assert path.read_text(encoding="utf-8") == "old cv"


def test_report_stamp_keeps_old_file(tmp_path, failing_swap):
    (tmp_path / "logs").mkdir()
    stamp = tmp_path / "logs" / recurring.STAMP
    stamp.write_text("old", encoding="utf-8")
    with pytest.raises(OSError):
        recurring.stamp_report(tmp_path)
    assert stamp.read_text(encoding="utf-8") == "old"


def test_init_keeps_old_config(tmp_path, failing_swap):
    from door.commands import profile as profile_cmd
    from door.core import workspace

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    config = profile_dir / "config.json"
    config.write_text((workspace.PROFILE_EXAMPLE_DIR / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    before = config.read_bytes()
    with pytest.raises(OSError):
        profile_cmd._init_core(
            {"name": "Ada", "email": "a@x.com", "location": "Copenhagen", "role_targets": ["analyst"]},
            profile_dir=profile_dir,
            example_dir=workspace.PROFILE_EXAMPLE_DIR,
        )
    assert config.read_bytes() == before


def test_new_file_mode_never_touches_the_umask(tmp_path, monkeypatch):
    from door.core import utils

    def no(*_a):
        raise AssertionError("os.umask called during a write")

    monkeypatch.setattr(os, "umask", no)
    path = tmp_path / "new.txt"
    utils.write_atomic(path, "x")
    assert path.stat().st_mode & 0o777 == 0o666 & ~utils._UMASK
