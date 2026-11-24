"""What a phone may ask `door serve` for (#302). A paired phone is not a Claude Code session on this
machine: it gets the tools the phone app uses and nothing else, never a local file path, and no prompt to Claude (`ask`).

`refusal(tool, args)` says why a call is refused, or None. `serve_http` asks it for every `tools/call`.
"""

from __future__ import annotations

# The tools the phone app calls (app/src/renderer through app/src/web/bridge.ts), and only those: it
# finds new jobs, prepares them and keeps the applications. Setting up, the profile, the CV and the
# employers are changed on the computer running The other door.
PHONE_TOOLS = frozenset({
    "status_summary", "list_matches", "show", "set_status", "mark_reviewed", "mark_seen", "import_posting",
    "find_jobs", "job_result", "cancel_job", "prepare", "revise", "show_profile",
})

_NOT_HERE = "the phone app does not use {tool}; do this on the computer running The other door"


def refusal(tool: str, args: dict) -> str | None:
    """Why a phone's call is refused, or None to let it through."""
    if tool not in PHONE_TOOLS:
        return _NOT_HERE.format(tool=tool)
    args = args or {}
    if tool == "import_posting":
        if args.get("path"):
            return "a phone cannot name a file on the computer running The other door; share or paste the ad instead"
    return None
