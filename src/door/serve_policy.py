"""What a phone may ask `door serve` for (#302, #544). A paired phone is not a Claude Code session on this
machine: it gets the tools the phone app uses, with the arguments the app sends and nothing else, no local
file path, no prompt to Claude (`ask`), no free-text `revise`, and a daily ceiling on the tools that cost.

`refusal(tool, args)` says why a call is refused, or None. `mcp_server._DoorMCP.call_tool` asks it first for
every call when the server runs for a phone (`mcp_server.serve_phone`).
"""

from __future__ import annotations

import threading
import time

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
    if args.get("path") and tool == "import_posting":
        return "a phone cannot name a file on the computer running The other door; share or paste the ad instead"
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
