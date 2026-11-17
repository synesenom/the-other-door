"""The one step that downloads a file pinned by sha256 (#202): the Chromium shell (`core/chromium`), cloudflared
(`core/phone`) and the CV fonts (`core/fonts`).

A caller opens a `staging` folder (a unique `.part` folder inside its destination, removed afterwards, the ones a
killed install left swept first), `download`s its pinned files into it, each checked against its sha256, and then
does its own steps (unpack, extract, chmod) and moves the result in. A failure leaves the destination as it was.
`http_get` is the one network call, the one place a test replaces.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# An install takes minutes; a staging folder older than this was left by one that was killed.
STALE_PART_SECONDS = 3600


class ChecksumError(ValueError):
    pass


def http_get(url: str, to: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, open(to, "wb") as out:  # noqa: S310 - https, pinned
        shutil.copyfileobj(response, out)


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sweep_stale_parts(dest: Path) -> None:
    """Remove the staging folders a killed install left in `dest`, never one still in use."""
    cutoff = time.time() - STALE_PART_SECONDS
    for part in Path(dest).glob("*.part"):
        if part.is_dir() and part.stat().st_mtime < cutoff:
            shutil.rmtree(part, ignore_errors=True)


@contextmanager
def staging(dest: Path, prefix: str) -> Iterator[Path]:
    """A staging folder unique to this process inside `dest` (made if missing), so two installs never share a
    half-written file; removed when the block ends, whatever happened."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    sweep_stale_parts(dest)
    folder = Path(tempfile.mkdtemp(prefix=prefix, suffix=".part", dir=dest))
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def download(items, folder: Path, fetch=None) -> None:
    """Fetch each `(url, name, sha256)` of `items` to `folder / name` and check it against its pin.

    Raises:
        ChecksumError: a file does not match its pin.
        OSError: a download failed.
    """
    get = fetch or http_get
    for url, name, digest in items:
        get(url, Path(folder) / name)
        if sha256(Path(folder) / name) != digest:
            raise ChecksumError(f"{name} does not match the pinned checksum; nothing was written")
