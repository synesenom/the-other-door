"""Shared utility helpers for The other door."""

import glob
import html
import json
import os
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# An install takes minutes; a staging folder older than this was left by one that was killed.
STALE_PART_SECONDS = 3600


def _sweep_stale_parts(dest: Path, prefix: str) -> None:
    """Remove the `prefix` staging folders a killed install left in `dest`, never one still in use, and never
    another tool's (cloudflared's `dest` is the shared ~/.local/bin)."""
    cutoff = time.time() - STALE_PART_SECONDS
    for part in Path(dest).glob(f"{glob.escape(prefix)}*.part"):
        if part.is_dir() and part.stat().st_mtime < cutoff:
            shutil.rmtree(part, ignore_errors=True)


@contextmanager
def staging(dest: Path, prefix: str) -> Iterator[Path]:
    """A staging folder unique to this process inside `dest` (made if missing), so two installs never share a
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


def write_json_atomic(path: Path, data, *, indent: int | None = 2, default=str) -> None:
    """Write `data` as JSON to `path` atomically: a temp file, then `os.replace`.

    A reader never sees a half-written file, and a failed write leaves the old
    file (and no temp file) behind. The parent directory is created; the temp
    name is unique per process and thread, so concurrent writers never share it.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False, default=default), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
