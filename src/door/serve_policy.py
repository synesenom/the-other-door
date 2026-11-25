"""What a phone may ask `door serve` for (#302, #544). A paired phone is not a Claude Code session on this
machine: it gets the tools the phone app uses, with the arguments the app sends and nothing else, no local
file path, no prompt to Claude (`ask`), no free-text `revise`, and a daily ceiling on the tools that cost.

`refusal(tool, args)` says why a call is refused, or None. `mcp_server._DoorMCP.call_tool` asks it first for
every call when the server runs for a phone (`mcp_server.serve_phone`), and passes every answer and error through
`answer` / `mask` (#546): the phone gets no folder of this computer, no Drive account, no computer-only setting.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from door.core import workspace

# The tools the phone app calls (app/src/renderer through app/src/web/bridge.ts), each with the argument
# names the app sends. Setting up, the profile, the CV, the employers, revising and "I'm done" are done on
# the computer running The other door.
PHONE_TOOLS: dict[str, frozenset[str]] = {
    "status_summary": frozenset(),
    "show_profile": frozenset(),
    "find_jobs": frozenset(),
    "cancel_job": frozenset(),
    "list_matches": frozenset({"ongoing", "closed"}),
    "show": frozenset({"job_id"}),
    "mark_seen": frozenset({"job_id"}),
    "job_result": frozenset({"tool"}),
    "set_status": frozenset({"job_id", "status", "notes"}),
    "prepare": frozenset({"job_id", "force"}),
    "import_posting": frozenset({"text", "url", "title", "company", "location", "force"}),
}

# The profile settings the phone shows (name, email, the search) and the ones the page it prints reads; every other
# key (paths, the Claude folder, the Drive and discovery choices, the employer lists) stays on the computer.
PHONE_PROFILE_KEYS = frozenset({
    "name", "email", "location", "needs_work_permit", "role_targets", "search_keywords", "topic_terms", "remote",
    "min_score", "exclude", "languages", "cv_accent", "cv_fonts", "max_age_days", "preferences",
})
_REASON_MAX = 400

# The longest string a phone may send: a pasted ad (as `commands/add._READ_MAX_CHARS`), a note, a link, any other.
_CAPS = {"text": 30000, "notes": 2000, "url": 2000}
_OTHER_CAP = 300

# Calls a phone may make in a rolling 24 hours: each one costs the Claude plan or the sites.
PHONE_DAILY = {"prepare": 10, "import_posting": 30, "find_jobs": 6}
_DAY = 24 * 3600.0

_NOT_HERE = "the phone app does not use {tool}; do this on the computer running The other door"
_clock = time.time
_calls: dict[str, list[float]] = {}
_lock = threading.Lock()


def reset() -> None:
    """Forget the calls counted (a test starts over)."""
    with _lock:
        _calls.clear()


def refusal(tool: str, args) -> str | None:
    """Why a phone's call is refused, or None to let it through (and count it against its daily ceiling)."""
    allowed = PHONE_TOOLS.get(tool)
    if allowed is None:
        return _NOT_HERE.format(tool=tool)
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return f"{tool} takes its arguments by name"
    extra = sorted(str(k) for k in args if k not in allowed)
    if extra:
        return f"the phone app does not send {', '.join(extra)} to {tool}; do this on the computer running The other door"
    for key, value in args.items():
        if isinstance(value, str) and len(value) > _CAPS.get(key, _OTHER_CAP):
            return f"{key} is too long for the phone; do this on the computer running The other door"
    limit = PHONE_DAILY.get(tool)
    if limit is not None:
        now = _clock()
        with _lock:
            recent = [t for t in _calls.get(tool, []) if now - t < _DAY]
            if len(recent) >= limit:
                _calls[tool] = recent
                return "the phone's daily limit for this is reached: try again tomorrow, or do it on the computer"
            recent.append(now)
            _calls[tool] = recent
    return None


def _folders() -> list[str]:
    """The folders of this computer a phone must not read, longest first (the data folder sits inside home)."""
    from door.commands import report  # a top-level module may import commands; not the other way round

    found = [workspace.HOME, workspace.REPO_ROOT, Path.home()] + ([os.environ["DOOR_HOME"]] if os.environ.get("DOOR_HOME") else [])
    return sorted({s for folder in found for s in report._spellings(folder)}, key=len, reverse=True)


def mask(text: str) -> str:
    """`text` without the folders of this computer: only the folder part goes, so a file's name stays."""
    for folder in _folders():
        text = text.replace(folder, "")
    return text


def _clean(value, folders: list[str]):
    """Every string of an answer (nested) without the folders, a score's reason cut to what a card shows."""
    if isinstance(value, str):
        for folder in folders:
            value = value.replace(folder, "")
        return value
    if isinstance(value, list):
        return [_clean(v, folders) for v in value]
    if isinstance(value, dict):
        out = {}
        for key, v in value.items():
            if key == "score_reason" and isinstance(v, str):
                v = v[:_REASON_MAX]
            out[key] = _clean(v, folders)
        return out
    return value


def answer(tool: str, data):
    """What a phone is sent of a tool's answer: the profile without its paths and computer-only settings, no Drive
    account, every folder of this computer masked."""
    if isinstance(data, dict):
        if tool == "show_profile" and "error" not in data:
            config = data.get("config")
            if isinstance(config, dict):
                config = {k: v for k, v in config.items() if k in PHONE_PROFILE_KEYS}
            cv = data.get("cv")
            data = {
                "config": config,
                "errors": data.get("errors"),
                "cv": {k: v for k, v in cv.items() if k != "path"} if isinstance(cv, dict) else cv,
                "discovery_unchosen": data.get("discovery_unchosen"),
            }
        elif tool == "status_summary" and isinstance(data.get("drive"), dict):
            data = {**data, "drive": {**data["drive"], "account": None}}
    return _clean(data, _folders())
