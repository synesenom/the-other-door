"""One staging folder for every staged write (#270): the pinned downloads and the data import."""

from __future__ import annotations

import os
import time

import pytest

from door.core import utils


def test_a_staging_folder_is_a_part_folder_inside_dest_removed_afterwards(tmp_path):
    dest = tmp_path / "dest"
    with utils.staging(dest, "x.") as stage:
        assert stage.parent == dest and stage.name.startswith("x.") and stage.name.endswith(".part")
        (stage / "half").write_bytes(b"1")
    assert list(dest.iterdir()) == []


def test_a_staging_folder_is_removed_when_the_step_fails(tmp_path):
    with pytest.raises(OSError), utils.staging(tmp_path, "x."):
        raise OSError("boom")
    assert list(tmp_path.iterdir()) == []


def _aged(path, seconds):
    path.mkdir()
    old = time.time() - seconds
    os.utime(path, (old, old))
    return path


def test_staging_sweeps_its_own_stale_part_folders_and_keeps_a_fresh_one(tmp_path):
    stale = _aged(tmp_path / "x.a.part", 2 * utils.STALE_PART_SECONDS)
    fresh = _aged(tmp_path / "x.b.part", 0)
    with utils.staging(tmp_path, "x."):
        assert not stale.exists() and fresh.exists()


def test_staging_leaves_another_tools_stale_part_folder_alone(tmp_path):
    """A shared destination (an import's HOME parent) may hold another tool's `.part` folder."""
    foreign = _aged(tmp_path / "other.a.part", 2 * utils.STALE_PART_SECONDS)
    with utils.staging(tmp_path, "x."):
        pass
    assert foreign.exists()
