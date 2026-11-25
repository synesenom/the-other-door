"""A well-scored ad written as Markdown: its headings and lists set out, its words the ad's own.

For a posting that cleared ``min_score`` (or an application in play) one Haiku call (`ad-layout` prompt,
feature ``ad_layout``) reads the ad and writes it back as Markdown: ``## `` headings, ``- `` list items,
blank lines between blocks, a line the page split from the one before put back with it. Code keeps the
answer only when its words are the ad's, every one, in the same order (`same_words`); the Markdown marks
and punctuation may differ, nothing else. It then stores it as the description and sets ``formatted``, so
it is done once. A failed call or a changed word leaves the plain text; the next run tries again.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from door.core import claude_cli, utils

_SCHEMA = {"type": "object", "properties": {"markdown": {"type": "string"}}, "required": ["markdown"]}
_MAX_CHARS = 30000
_WORD = re.compile(r"\w+")


def same_words(description: str, markdown: str) -> bool:
    """Whether ``markdown`` holds the description's words, every one and in the same order."""
    return _WORD.findall(description or "") == _WORD.findall(markdown or "")


def needs_layout(posting: dict) -> bool:
    """Whether the posting has text not yet written as Markdown."""
    return bool((posting.get("description") or "").strip()) and not posting.get("formatted")


def lay_out(path: Path, *, profile_dir: Path | None = None) -> bool:
    """Write the description of the posting at ``path`` as Markdown when it is not yet; True when it was.
    A failed call, or an answer whose words are not the ad's, changes nothing."""
    posting = json.loads(Path(path).read_text(encoding="utf-8"))
    if not needs_layout(posting):
        return False
    description = posting.get("description") or ""
    if len(description) > _MAX_CHARS:
        return False
    try:
        answer = claude_cli.ask("ad-layout", description, feature="ad_layout", schema=_SCHEMA, timeout_s=180,
                                profile_dir=profile_dir)
    except claude_cli.ClaudeError:
        return False
    markdown = answer.get("markdown") if isinstance(answer, dict) else None
    if not isinstance(markdown, str) or not same_words(description, markdown):
        return False
    posting["description"] = markdown.strip()
    posting["formatted"] = True
    utils.write_json_atomic(Path(path), posting)
    return True
