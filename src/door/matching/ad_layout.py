"""A well-scored ad written as Markdown: its headings and lists marked, its words the ad's own.

A scraped description is one line per block of the ad. For a posting that cleared ``min_score`` one
Haiku call (`ad-layout` prompt, feature ``ad_layout``) reads the numbered lines and names the headings
and bullets by number; the model writes no text. Code keeps only integers in range and a line in one
list only, writes the description back as Markdown (``## `` before a heading, ``- `` before a list
item, a blank line between blocks) and sets ``formatted`` on the posting, so it is done once. A failed
call leaves the raw text; the next run tries again.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from door.core import claude_cli, utils

_SCHEMA = {
    "type": "object",
    "properties": {
        "headings": {"type": "array", "items": {"type": "integer"}},
        "bullets": {"type": "array", "items": {"type": "integer"}},
        "joins": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["headings", "bullets", "joins"],
}
_MAX_CHARS = 30000
_MARKER = re.compile(r"^\s*(?:[-*•–·]|\d+[.)])\s+")


def lines(description: str) -> list[str]:
    """The description's non-empty lines, stripped: the lines the layout numbers (from 1)."""
    return [line.strip() for line in (description or "").splitlines() if line.strip()]


def verified(answer, count: int) -> dict:
    """``{"headings", "bullets", "joins"}`` from a model's answer: sorted integers in 1..count, once each, a
    line named as both heading and bullet in neither, a join never the first line."""
    def ints(key: str) -> set[int]:
        raw = answer.get(key) if isinstance(answer, dict) else None
        return {n for n in raw if type(n) is int and 1 <= n <= count} if isinstance(raw, list) else set()

    headings, bullets = ints("headings"), ints("bullets")
    both = headings & bullets
    return {"headings": sorted(headings - both), "bullets": sorted(bullets - both),
            "joins": sorted(n for n in ints("joins") if n > 1)}


def markdown(description: str, layout: dict) -> str:
    """The description as Markdown: a line `layout` names in ``joins`` put back at the end of the line before
    (the page split it, a list item's label from its text), then the headings and bullets marked, one blank
    line between blocks and none inside a list. The words are the description's."""
    headings, bullets = set(layout.get("headings") or []), set(layout.get("bullets") or [])
    joins = set(layout.get("joins") or [])
    rows: list[tuple[int, str]] = []
    for number, text in enumerate(lines(description), 1):
        if number in joins and rows:
            first, before = rows[-1]
            rows[-1] = (first, before + ("" if text[:1] in ":;,.)" else " ") + text)
        else:
            rows.append((number, text))
    out: list[str] = []
    previous = ""
    for number, text in rows:
        kind = "heading" if number in headings else "bullet" if number in bullets else "paragraph"
        line = f"## {text}" if kind == "heading" else f"- {_MARKER.sub('', text) or text}" if kind == "bullet" else text
        if out and not (kind == previous == "bullet"):
            out.append("")
        out.append(line)
        previous = kind
    return "\n".join(out)


def needs_layout(posting: dict) -> bool:
    """Whether the posting has text not yet written as Markdown."""
    return bool(lines(posting.get("description") or "")) and not posting.get("formatted")


def lay_out(path: Path, *, profile_dir: Path | None = None) -> bool:
    """Write the description of the posting at ``path`` as Markdown when it is not yet; True when it was.
    A failed call changes nothing."""
    posting = json.loads(Path(path).read_text(encoding="utf-8"))
    if not needs_layout(posting):
        return False
    description = posting.get("description") or ""
    rows = lines(description)
    text = "\n".join(f"{n}: {row}" for n, row in enumerate(rows, 1))[:_MAX_CHARS]
    try:
        answer = claude_cli.ask("ad-layout", text, feature="ad_layout", schema=_SCHEMA, timeout_s=120,
                                profile_dir=profile_dir)
    except claude_cli.ClaudeError:
        return False
    if not isinstance(answer, dict):
        return False
    posting["description"] = markdown(description, verified(answer, len(rows)))
    posting["formatted"] = True
    utils.write_json_atomic(Path(path), posting)
    return True
