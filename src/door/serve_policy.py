"""What a phone may ask `door serve` for (#302). A paired phone is not a Claude Code session on this
machine: it gets the tools the phone app uses and nothing else, never a local file path, never an
address on this machine or the home network, and no prompt to Claude (`ask`).

`refusal(tool, args)` says why a call is refused, or None. `serve_http` asks it for every `tools/call`.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

# The tools the phone app calls (app/src/renderer through app/src/web/bridge.ts), and only those: it
# finds new jobs, prepares them and keeps the applications. Setting up, the profile, the CV and the
# employers are changed on the computer running The other door.
PHONE_TOOLS = frozenset({
    "status_summary", "list_matches", "show", "set_status", "mark_reviewed", "mark_seen", "import_posting",
    "find_jobs", "job_result", "cancel_job", "prepare", "revise", "show_profile",
})

_NOT_HERE = "the phone app does not use {tool}; do this on the computer running The other door"


def _host_is_private(host: str, resolve) -> bool:
    """True for this machine, the home network, link-local and the like (a name resolving there too)."""
    host = host.strip("[]").lower()
    if host in ("localhost",) or host.endswith((".local", ".localhost", ".internal", ".lan", ".home.arpa")):
        return True
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in resolve(host, None)]
        except (OSError, UnicodeError, ValueError):
            return False  # unknown here: the tool will say it could not be read
    return any(not a.is_global for a in addresses)


def _url_refusal(value: str, resolve) -> str | None:
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return f"only web addresses (http or https) are read from the phone: {value!r}"
    if _host_is_private(parts.hostname, resolve):
        return f"{parts.hostname} is on this machine or your home network; the phone cannot ask The other door to read it"
    return None


def refusal(tool: str, args: dict, *, resolve=socket.getaddrinfo) -> str | None:
    """Why a phone's call is refused, or None to let it through."""
    if tool not in PHONE_TOOLS:
        return _NOT_HERE.format(tool=tool)
    args = args or {}
    if tool == "import_posting":
        if args.get("path"):
            return "a phone cannot name a file on the computer running The other door; share or paste the ad instead"
        if args.get("url"):
            return _url_refusal(str(args["url"]), resolve)
    return None
