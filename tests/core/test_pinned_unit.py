"""The one pinned-download step (#202): fetch into a `.part` staging folder, check the sha256, leave the move to
the caller; Chromium, cloudflared and the fonts all go through it."""

from __future__ import annotations

import hashlib

import pytest

from door.core import pinned


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_sha256_is_the_hex_digest_of_the_file(tmp_path):
    path = tmp_path / "f"
    path.write_bytes(b"abc")
    assert pinned.sha256(path) == _sha(b"abc")


def test_download_fetches_each_item_into_the_folder_checked(tmp_path, monkeypatch):
    files = {"https://h/a": b"A", "https://h/b": b"B"}
    monkeypatch.setattr(pinned, "http_get", lambda url, to: to.write_bytes(files[url]))
    pinned.download([(url, url[-1], _sha(data)) for url, data in files.items()], tmp_path)
    assert (tmp_path / "a").read_bytes() == b"A" and (tmp_path / "b").read_bytes() == b"B"


def test_download_refuses_a_file_that_does_not_match_its_pin(tmp_path, monkeypatch):
    monkeypatch.setattr(pinned, "http_get", lambda url, to: to.write_bytes(b"A"))
    with pytest.raises(pinned.ChecksumError, match="b does not match the pinned checksum"):
        pinned.download([("https://h/a", "a", _sha(b"A")), ("https://h/b", "b", _sha(b"B"))], tmp_path)
