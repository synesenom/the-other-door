"""The layout of a well-scored ad: which of its lines are headings and which are list items.

A scraped description is one line per block of the ad. For a posting that cleared ``min_score`` one
Haiku call (`ad-layout` prompt, feature ``ad_layout``) reads the numbered lines and names the headings
and bullets by number; the model writes no text. Code keeps only integers in range and a line in one
list only, and stores them on the posting as ``layout`` beside the sha256 of the description they were
made for, so a layout of an older description is ignored. A failed call leaves the raw text; the next
run tries again, since "no layout for this description" is the only test.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from door.core import claude_cli, utils

_SCHEMA = {
    "type": "object",
    "properties": {
        "headings": {"type": "array", "items": {"type": "integer"}},
        "bullets": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["headings", "bullets"],
}
_MAX_CHARS = 30000
_MARKER = re.compile(r"^\s*(?:[-*•–·]|\d+[.)])\s+")


def lines(description: str) -> list[str]:
    """The description's non-empty lines, stripped: the lines the layout numbers (from 1)."""
    return [line.strip() for line in (description or "").splitlines() if line.strip()]


def description_hash(description: str) -> str:
    return hashlib.sha256((description or "").encode("utf-8")).hexdigest()


def verified(answer, count: int) -> dict:
    """``{"headings", "bullets"}`` from a model's answer: sorted integers in 1..count, once each, a line
    named in both lists in neither."""
    def ints(key: str) -> set[int]:
        raw = answer.get(key) if isinstance(answer, dict) else None
        return {n for n in raw if type(n) is int and 1 <= n <= count} if isinstance(raw, list) else set()

    headings, bullets = ints("headings"), ints("bullets")
    both = headings & bullets
    return {"headings": sorted(headings - both), "bullets": sorted(bullets - both)}


def _made_for(description: str, layout) -> bool:
    """Whether ``layout`` was made for this very description."""
    return isinstance(layout, dict) and layout.get("sha256") == description_hash(description)


def blocks(description: str, layout: dict | None) -> list[dict]:
    """The description as ``[{"kind": "heading"|"bullet"|"paragraph", "text"}]``, one per non-empty line.
    Without a layout made for this very description every line is a paragraph."""
    rows = lines(description)
    valid = _made_for(description, layout)
    headings = set(layout.get("headings") or []) if valid else set()
    bullets = set(layout.get("bullets") or []) if valid else set()
    out = []
    for number, text in enumerate(rows, 1):
        if number in headings:
            out.append({"kind": "heading", "text": text})
        elif number in bullets:
            out.append({"kind": "bullet", "text": _MARKER.sub("", text) or text})
        else:
            out.append({"kind": "paragraph", "text": text})
    return out


def lay_out(path: Path, *, profile_dir: Path | None = None) -> bool:
    """Give the posting at ``path`` a layout when it has none for its description; True when it got one.
    A failed call changes nothing."""
    posting = json.loads(Path(path).read_text(encoding="utf-8"))
    description = posting.get("description") or ""
    rows = lines(description)
    if not rows or _made_for(description, posting.get("layout")):
        return False
    text = "\n".join(f"{n}: {row}" for n, row in enumerate(rows, 1))[:_MAX_CHARS]
    try:
        answer = claude_cli.ask("ad-layout", text, feature="ad_layout", schema=_SCHEMA, timeout_s=120,
                                profile_dir=profile_dir)
    except claude_cli.ClaudeError:
        return False
    if not isinstance(answer, dict):
        return False
    posting["layout"] = {**verified(answer, len(rows)), "sha256": description_hash(description)}
    utils.write_json_atomic(Path(path), posting)
    return True
