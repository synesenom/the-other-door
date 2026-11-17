"""The one pinned-download step (#202): fetch into a `.part` staging folder, check the sha256, leave the move to
the caller; Chromium, cloudflared and the fonts all go through it."""

from __future__ import annotations

import hashlib
import os
import time

import pytest

from door.core import pinned


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_sha256_is_the_hex_digest_of_the_file(tmp_path):
    path = tmp_path / "f"
    path.write_bytes(b"abc")
    assert pinned.sha256(path) == _sha(b"abc")


def test_a_staging_folder_is_a_part_folder_inside_dest_removed_afterwards(tmp_path):
    dest = tmp_path / "dest"
    with pinned.staging(dest, "x.") as stage:
        assert stage.parent == dest and stage.name.startswith("x.") and stage.name.endswith(".part")
        (stage / "half").write_bytes(b"1")
    assert list(dest.iterdir()) == []


def test_a_staging_folder_is_removed_when_the_step_fails(tmp_path):
    with pytest.raises(OSError), pinned.staging(tmp_path, "x."):
        raise OSError("boom")
    assert list(tmp_path.iterdir()) == []


def _aged(path, seconds):
    path.mkdir()
    old = time.time() - seconds
    os.utime(path, (old, old))
    return path


def test_staging_sweeps_its_own_stale_part_folders_and_keeps_a_fresh_one(tmp_path):
    stale = _aged(tmp_path / "x.a.part", 2 * pinned.STALE_PART_SECONDS)
    fresh = _aged(tmp_path / "x.b.part", 0)
    with pinned.staging(tmp_path, "x."):
        assert not stale.exists() and fresh.exists()


def test_staging_leaves_another_tools_stale_part_folder_alone(tmp_path):
    """A shared destination (cloudflared's ~/.local/bin) may hold another tool's `.part` folder."""
    foreign = _aged(tmp_path / "other.a.part", 2 * pinned.STALE_PART_SECONDS)
    with pinned.staging(tmp_path, "x."):
        pass
    assert foreign.exists()


def test_download_fetches_each_item_into_the_folder_checked(tmp_path, monkeypatch):
    files = {"https://h/a": b"A", "https://h/b": b"B"}
    monkeypatch.setattr(pinned, "http_get", lambda url, to: to.write_bytes(files[url]))
    pinned.download([(url, url[-1], _sha(data)) for url, data in files.items()], tmp_path)
    assert (tmp_path / "a").read_bytes() == b"A" and (tmp_path / "b").read_bytes() == b"B"


def test_download_refuses_a_file_that_does_not_match_its_pin(tmp_path, monkeypatch):
    monkeypatch.setattr(pinned, "http_get", lambda url, to: to.write_bytes(b"A"))
    with pytest.raises(pinned.ChecksumError, match="b does not match the pinned checksum"):
        pinned.download([("https://h/a", "a", _sha(b"A")), ("https://h/b", "b", _sha(b"B"))], tmp_path)
