"""Shared utility helpers for The other door."""

import json
import os
import re
import threading
from pathlib import Path


def _escape_latex(text: str) -> str:
    """Escape LaTeX special characters in untrusted text.

    Converts the ten LaTeX special characters so the text can be safely
    interpolated into a .tex document without triggering LaTeX commands.

    The ten characters and their replacements:
        \\  ->  \\textbackslash{}   (must be first to avoid double-escaping)
        &   ->  \\&
        %   ->  \\%
        $   ->  \\$
        #   ->  \\#
        _   ->  \\_
        {   ->  \\{
        }   ->  \\}
        ~   ->  \\~{}
        ^   ->  \\^{}
    """
    # Use a sentinel to avoid double-escaping: first swap backslashes for a
    # placeholder that contains no other special characters, escape all other
    # special characters, then replace the placeholder with \textbackslash{}.
    # The sentinel must be a string that cannot appear in normal text and does
    # not contain any of the special characters being escaped.
    _BACKSLASH_SENTINEL = "\x00BSLASH\x00"
    text = text.replace("\\", _BACKSLASH_SENTINEL)
    text = text.replace("&", r"\&")
    text = text.replace("%", r"\%")
    text = text.replace("$", r"\$")
    text = text.replace("#", r"\#")
    text = text.replace("_", r"\_")
    text = text.replace("{", r"\{")
    text = text.replace("}", r"\}")
    text = text.replace("~", r"\~{}")
    text = text.replace("^", r"\^{}")
    text = text.replace(_BACKSLASH_SENTINEL, r"\textbackslash{}")
    return text


def _normalize_text_for_ats(text: str) -> str:
    """Normalize typographic characters in *text* so ATS systems parse it cleanly.

    LLMs frequently emit fancy typographic characters that confuse applicant
    tracking systems when they extract plain text from PDFs.  This helper
    replaces each such character with its ASCII equivalent (or removes it)
    before the text is fed to ``_escape_latex``.

    Character classes handled (in order):
    1. Ligatures: ﬀ→ff, ﬁ→fi, ﬂ→fl, ﬃ→ffi, ﬄ→ffl
    2. Em-dash (U+2014) → " - "
    3. En-dash (U+2013) → "-"
    4. Smart double quotes (U+201C, U+201D) → '"'
    5. Smart single quotes / apostrophes (U+2018, U+2019) → "'"
    6. Zero-width chars (U+200B, U+200C, U+200D, U+FEFF) → removed

    Must be called **before** ``_escape_latex`` so that the ASCII replacements
    introduced here are not re-escaped by LaTeX escaping.
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
