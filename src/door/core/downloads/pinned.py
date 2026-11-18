"""The one step that downloads a file pinned by sha256 (#202): the Chromium shell (`core/chromium`), cloudflared
(`core/phone`) and the CV fonts (`style/fonts`).

A caller opens a `utils.staging` folder (a unique `.part` folder inside its destination, removed afterwards, the ones a
killed install left swept first), `download`s its pinned files into it, each checked against its sha256, and then
does its own steps (unpack, extract, chmod) and moves the result in. A failure leaves the destination as it was.
`http_get` is the one network call, looked up when `download` runs: the one place a test replaces.
"""

from __future__ import annotations

import hashlib
import shutil
import urllib.request
from pathlib import Path


class ChecksumError(ValueError):
    pass


def http_get(url: str, to: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, open(to, "wb") as out:  # noqa: S310 - https, pinned
        shutil.copyfileobj(response, out)


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def download(items, folder: Path) -> None:
    """Fetch each `(url, name, sha256)` of `items` to `folder / name` and check it against its pin.

    Raises:
        ChecksumError: a file does not match its pin.
        OSError: a download failed.
    """
    for url, name, digest in items:
        http_get(url, Path(folder) / name)
        if sha256(Path(folder) / name) != digest:
            raise ChecksumError(f"{name} does not match the pinned checksum; nothing was written")
