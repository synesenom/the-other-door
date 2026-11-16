"""Build a CV template from an uploaded CV (#149, epic #144): the builder core.

`build(pdf_path, ...)` reads the style of a CV PDF (`style_extract`), fetches the free fonts for it (`fonts`), writes its
icons as SVG files, and runs the stylist agent (`.claude/agents/stylist.md`) round by round: the agent writes a template
page, the builder checks it (`html_guard.template_problems`), prints a sample body in it with the pinned Chromium, reads
the print back and compares it with the original (`style_compare`) until the loop's rule says stop. The best round is
then stress-rendered with `profile/cv.md` made shorter, longer, French and with a photo (no model: `cv_body`), one more
round when that fails, and a second call writes the matching letter template. Only a build that passes is written, whole,
to `profile/style/`; a failed one writes nothing there.
"""

from __future__ import annotations

import re
from pathlib import Path

from door.core import workspace

STYLIST = "stylist"
_BLOCK = re.compile(r"^```(\w+)[ \t]*\n(.*?)\n```[ \t]*$", re.S | re.M)


def agent() -> dict:
    """The stylist agent's definition from `.claude/agents/stylist.md`: ``description``, ``model``, ``tools`` and its
    body as the ``prompt``."""
    text = (workspace.REPO_ROOT / ".claude" / "agents" / f"{STYLIST}.md").read_text(encoding="utf-8")
    _, front, body = text.split("---", 2)
    entry: dict = {"prompt": body.strip(), "tools": []}
    key = None
    for line in front.splitlines():
        if line.lstrip().startswith("- ") and key == "tools":
            entry["tools"].append(line.strip()[2:].strip())
        elif ":" in line and not line.startswith(" "):
            key, value = (part.strip() for part in line.split(":", 1))
            if key in ("description", "model"):
                entry[key] = value
    return entry


def blocks(reply: str) -> dict[str, str]:
    """The fenced blocks of a stylist's reply by their name (```` ```template ````, ``body``, ``letter``): the first of
    each name. A block cut off before its closing fence is not one."""
    found: dict[str, str] = {}
    for name, text in _BLOCK.findall(reply):
        found.setdefault(name, text.strip())
    return found
