"""Shared utility helpers for The other door."""

import glob
import html
import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# A staged write (an install, an import, a preview) takes minutes at most; a staging folder older than this was left by one that was killed.
STALE_PART_SECONDS = 3600


# A model's summary read in an info bubble (a match's reason, a salary's why): its prompt asks for at most 20 words;
# one past this, the model's whole working rather than a summary, is not shown.
BUBBLE_WORDS = 25


def bubble_text(text: str) -> str:
    """``text`` stripped, or "" when it is longer than `BUBBLE_WORDS` words."""
    text = (text or "").strip()
    return text if len(text.split()) <= BUBBLE_WORDS else ""


def _sweep_stale_parts(dest: Path, prefix: str) -> None:
    """Remove the `prefix` staging folders a killed staged write left in `dest`, never one still in use, and never
    another tool's (cloudflared's `dest` is the shared ~/.local/bin)."""
    cutoff = time.time() - STALE_PART_SECONDS
    for part in Path(dest).glob(f"{glob.escape(prefix)}*.part"):
        if part.is_dir() and part.stat().st_mtime < cutoff:
            shutil.rmtree(part, ignore_errors=True)


@contextmanager
def staging(dest: Path, prefix: str) -> Iterator[Path]:
    """A staging folder unique to this process inside `dest` (made if missing), so two staged writes (installs, imports, previews) never share a
    half-written file; removed when the block ends, whatever happened. The ones of `prefix` a killed install
    left are swept first."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    _sweep_stale_parts(dest, prefix)
    folder = Path(tempfile.mkdtemp(prefix=prefix, suffix=".part", dir=dest))
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _escape_html(text: str) -> str:
    """Escape untrusted text (a posting's title or company) so it is plain text inside an HTML body: `&`, `<`, `>` and
    both quotes become character references."""
    return html.escape(text, quote=True)


def _normalize_text_for_ats(text: str) -> str:
    """Normalize typographic characters in *text* so ATS systems parse it cleanly.

    LLMs frequently emit fancy typographic characters that confuse applicant
    tracking systems when they extract plain text from PDFs.  This helper
    replaces each such character with its ASCII equivalent (or removes it)
    before the text is fed to ``_escape_html``.

    Character classes handled (in order):
    1. Ligatures: ﬀ→ff, ﬁ→fi, ﬂ→fl, ﬃ→ffi, ﬄ→ffl
    2. Em-dash (U+2014) → " - "
    3. En-dash (U+2013) → "-"
    4. Smart double quotes (U+201C, U+201D) → '"'
    5. Smart single quotes / apostrophes (U+2018, U+2019) → "'"
    6. Zero-width chars (U+200B, U+200C, U+200D, U+FEFF) → removed

    Must be called **before** ``_escape_html``.
    """
    # 1. Ligatures
    text = text.replace("ﬀ", "ff")
    text = text.replace("ﬁ", "fi")
    text = text.replace("ﬂ", "fl")
    text = text.replace("ﬃ", "ffi")
    text = text.replace("ﬄ", "ffl")
    # 2. Em-dash
    text = text.replace("—", " - ")
    # 3. En-dash
    text = text.replace("–", "-")
    # 4. Smart double quotes
    text = text.replace("“", '"')
    text = text.replace("”", '"')
    # 5. Smart single quotes / apostrophes
    text = text.replace("‘", "'")
    text = text.replace("’", "'")
    # 6. Zero-width characters (remove)
    text = text.replace("​", "")
    text = text.replace("‌", "")
    text = text.replace("‍", "")
    text = text.replace("﻿", "")
    return text


def _validate_job_id(job_id: str) -> None:
    """Validate a job_id before using it to construct a filesystem path.

    Accepts only dot-separated segments matching ``[a-z0-9][a-z0-9_-]*`` (the
    ``<site>.<platform_id>`` ids of ``make_job_id`` in src/door/core/models.py,
    the platform id normalised to ``[a-z0-9_-]``).

    Raises:
        ValueError: with the message "invalid job_id" if the value contains
            path traversal sequences (``..``), starts with ``/`` or ``.``, or
            contains characters outside ``[a-z0-9._-]``.
    """
    if not job_id or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)*", job_id):
        raise ValueError(f"invalid job_id: {job_id!r}")


# Read once: `os.umask` can only be read by setting it, which races with other threads' file creation.
_UMASK = os.umask(0)
os.umask(_UMASK)


@contextmanager
def atomic_target(path: Path, *, mode: int | None = None):
    """Yield a unique temp file beside `path`; on a clean exit `os.replace` it onto `path`.

    The parent directory is created. The temp file has `mode` before anything is written (never
    readable by others, even briefly); without `mode` it keeps the existing file's mode, else
    `0o666 & ~umask` (what `write_text` gave). A failed block leaves the old file, and the temp
    file is always removed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            mode = 0o666 & ~_UMASK
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    os.close(fd)
    tmp = Path(name)
    try:
        os.chmod(tmp, mode)
        yield tmp
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_atomic(path: Path, data: str | bytes, *, mode: int | None = None) -> None:
    """Write text (UTF-8) or bytes to `path` atomically, through `atomic_target`."""
    with atomic_target(path, mode=mode) as tmp:
        if isinstance(data, bytes):
            tmp.write_bytes(data)
        else:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(data)


def write_json_atomic(path: Path, data, *, indent: int | None = 2, default=str) -> None:
    """Write `data` as JSON to `path` through `write_atomic`."""
    write_atomic(path, json.dumps(data, indent=indent, ensure_ascii=False, default=default))


def fair_share(items: list, limit: int, *, key, rank=None) -> tuple[list, list]:
    """``(chosen, rest)``: at most *limit* of *items*, taken round-robin over the groups *key* names (the group with the
    best item first), the lowest *rank* first within each group (in their order without one). One flooded group cannot crowd out the
    others, a cap's whole purpose. Pure."""
    groups: dict = {}
    for item in sorted(items, key=rank) if rank else items:
        groups.setdefault(key(item), []).append(item)
    chosen: list = []
    queues = [iter(g) for g in groups.values()]
    while queues and len(chosen) < limit:
        for queue in list(queues):
            item = next(queue, None)
            if item is None:
                queues.remove(queue)
                continue
            chosen.append(item)
            if len(chosen) >= limit:
                break
    taken = {id(i) for i in chosen}
    return chosen, [i for i in items if id(i) not in taken]
