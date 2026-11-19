#!/usr/bin/env python3
"""Write a table of contents into every long Markdown doc, between `<!-- toc -->` markers.

A doc gets one when it is at least `MIN_LINES` long and has at least `MIN_ENTRIES` `##`/`###`
headings. The contents go just before its first `##` heading, or replace the existing block.
`tests/scripts/test_toc_unit.py` fails until every one is current.

    python3 scripts/toc.py
"""

import re
import subprocess
from pathlib import Path

MIN_LINES = 200
MIN_ENTRIES = 4
START, END = "<!-- toc -->", "<!-- /toc -->"
# Not read as docs: Claude's instructions and prompts, and the journey inventories that app/journeys/inventory.ts parses.
SKIP = ("CLAUDE.md", ".claude/", "app/journeys/inventory/")

_BLOCK = re.compile(re.escape(START) + r".*?" + re.escape(END) + r"\n*", re.S)
_HEADING = re.compile(r"^(##|###) (.+?)\s*$")


def anchor(title: str) -> str:
    """GitHub's anchor of a heading: the text without its markup, lowercase, punctuation dropped, spaces as dashes."""
    text = title.replace("`", "").replace("*", "")
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def _headings(text: str) -> list[tuple[int, str]]:
    found, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and (m := _HEADING.match(line)):
            found.append((len(m.group(1)), m.group(2)))
    return found


def wants_toc(text: str) -> bool:
    return len(_BLOCK.sub("", text).splitlines()) >= MIN_LINES and len(_headings(text)) >= MIN_ENTRIES


def with_toc(text: str) -> str:
    """The text with its contents written (or rewritten) before the first `##` heading."""
    body = _BLOCK.sub("", text)
    lines = [f"{'  ' * (level - 2)}- [{title}](#{anchor(title)})" for level, title in _headings(body)]
    block = f"{START}\n**Contents**\n\n" + "\n".join(lines) + f"\n{END}\n\n"
    at = re.search(r"^## ", body, re.M)
    return body[: at.start()] + block + body[at.start():]


def stale(root: Path) -> list[Path]:
    """The long docs whose contents are missing or out of date."""
    names = subprocess.run(["git", "ls-files", "*.md"], cwd=root, capture_output=True, text=True, check=True).stdout
    out = []
    for name in names.split():
        path = root / name
        text = path.read_text(encoding="utf-8")
        if not name.startswith(SKIP) and wants_toc(text) and with_toc(text) != text:
            out.append(path)
    return out


if __name__ == "__main__":
    for path in stale(Path(__file__).resolve().parent.parent):
        path.write_text(with_toc(path.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"wrote contents: {path}")
