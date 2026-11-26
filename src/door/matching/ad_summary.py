"""A short, checked summary of an ad, for a Claude Code chat that never reads the ad itself.

An ad is written by a stranger and a chat can run commands on the user's computer, so a request in the ad's text to
be ignored is only a request. In a chat `show` hands Claude this summary instead of the description: one tool-less
Haiku call (`ad-summary` prompt, feature ``ad_summary``) extracts it, and code cuts every field to its bounds
(`clean`): a value of the wrong type is dropped, newlines become spaces, a long value is cut, a list is capped.
The posting keeps the answer in its ``summary`` field with the sha256 of the description it was made from, so an
edited ad is summarised again. A failed call is no summary (``None``), never the description.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from door.core import claude_cli, lock, utils

_LISTS = {"requirements": (12, 80), "nice_to_have": (8, 80), "languages": (5, 40)}
_TEXTS = {"salary": 80, "place": 80, "seniority": 40}
_WORK_MODES = ("onsite", "hybrid", "remote")
_MAX_CHARS = 30000

_STRING = {"type": ["string", "null"]}
_SCHEMA = {
    "type": "object",
    "properties": {
        "requirements": {"type": "array", "items": {"type": "string"}},
        "nice_to_have": {"type": "array", "items": {"type": "string"}},
        "salary": _STRING,
        "place": _STRING,
        "work_mode": {"type": ["string", "null"], "enum": [*_WORK_MODES, None]},
        "languages": {"type": "array", "items": {"type": "string"}},
        "seniority": _STRING,
    },
    "required": ["requirements", "nice_to_have", "salary", "place", "work_mode", "languages", "seniority"],
}


def _line(value, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())[:limit].strip()
    return text or None


def clean(answer) -> dict:
    """The model's answer cut to the summary's bounds; every field is there, empty when it was not usable."""
    answer = answer if isinstance(answer, dict) else {}
    out: dict = {}
    for key, (count, limit) in _LISTS.items():
        items = answer.get(key) if isinstance(answer.get(key), list) else []
        out[key] = [line for line in (_line(i, limit) for i in items) if line][:count]
    for key, limit in _TEXTS.items():
        out[key] = _line(answer.get(key), limit)
    mode = answer.get("work_mode")
    out["work_mode"] = mode if mode in _WORK_MODES else None
    return out


def _sha(description: str) -> str:
    return hashlib.sha256(description.encode("utf-8")).hexdigest()


def cached(posting: dict) -> dict | None:
    """The stored summary when it was made from the posting's present description."""
    block = posting.get("summary")
    if isinstance(block, dict) and block.get("sha256") == _sha(str(posting.get("description") or "")):
        fields = block.get("fields")
        return clean(fields) if isinstance(fields, dict) else None
    return None


def summarise(posting: dict, path: Path | None, *, jobs_dir: Path, profile_dir: Path | None = None) -> dict:
    """``{"summary": dict | None, "warning"?: str}`` for ``posting`` (stored at ``path``): the cached one, else one
    model call whose answer is stored on the posting file (under the ledger lock; a busy lock only skips the
    storing). The description is never part of the answer."""
    have = cached(posting)
    if have is not None:
        return {"summary": have}
    description = str(posting.get("description") or "")
    if not description.strip():
        return {"summary": clean({})}
    try:
        if len(description) > _MAX_CHARS:
            raise claude_cli.ClaudeError("the ad is too long to summarise")
        answer = claude_cli.ask("ad-summary", description, feature="ad_summary", schema=_SCHEMA, timeout_s=120,
                                profile_dir=profile_dir)
        if not isinstance(answer, dict):
            raise claude_cli.ClaudeError("the answer was not a summary")
    except claude_cli.ClaudeError as exc:
        return {"summary": None, "warning": f"no summary of the ad this time ({exc}); open the ad in the browser to read it"}
    fields = clean(answer)
    if path is not None:
        try:
            with lock.ledger_lock(jobs_dir, "ad_summary"):
                stored = json.loads(Path(path).read_text(encoding="utf-8"))
                stored["summary"] = {"sha256": _sha(description), "fields": fields}
                utils.write_json_atomic(Path(path), stored)
        except (lock.LockHeldError, OSError, ValueError):
            pass  # not stored this time: the next `show` asks again
    return {"summary": fields}
