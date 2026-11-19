#!/usr/bin/env python3
"""Write a table of contents into every long Markdown doc, between `<!-- toc -->` markers.

A doc gets one when it is at least `MIN_LINES` long and has at least `MIN_ENTRIES` `##`/`###`
headings. The contents go just before its first `##` heading, or replace the existing block.
`--check` writes nothing and exits 1 when a doc's contents are missing or out of date
(`tests/scripts/test_toc_unit.py` runs the same check).

    python scripts/toc.py [--check]
"""

import re
import subprocess
import sys
from pathlib import Path

MIN_LINES = 200
MIN_ENTRIES = 4
START, END = "<!-- toc -->", "<!-- /toc -->"
# Not read as docs: Claude's instructions, and the journey inventories that app/journeys/inventory.ts parses.
SKIP = ("CLAUDE.md", "app/journeys/inventory/", "tests/", "thoughts/", "profile.example/", ".claude/")

_BLOCK = re.compile(re.escape(START) + r".*?" + re.escape(END) + r"\n*", re.S)
_HEADING = re.compile(r"^(##|###) (.+?)\s*#*\s*$")


def anchor(title: str) -> str:
    """GitHub's anchor of a heading: the text without its markup, lowercase, punctuation dropped, spaces as dashes."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title).replace("`", "").replace("*", "")
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
    heads = _headings(text)
    return (len(_BLOCK.sub("", text).splitlines()) >= MIN_LINES and len(heads) >= MIN_ENTRIES
            and any(level == 2 for level, _ in heads))


def with_toc(text: str) -> str:
    """The text with its contents written (or rewritten) before the first `##` heading."""
    body = _BLOCK.sub("", text)
    used: dict[str, int] = {}
    lines = []
    for level, title in _headings(body):
        slug = anchor(title)
        n = used.get(slug, 0)
        used[slug] = n + 1
        label = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title)
        lines.append(f"{'  ' * (level - 2)}- [{label}](#{slug}{f'-{n}' if n else ''})")
    block = f"{START}\n**Contents**\n\n" + "\n".join(lines) + f"\n{END}\n\n"
    at = re.search(r"^## ", body, re.M)
    return body[: at.start()] + block + body[at.start():]


def _docs(root: Path) -> list[Path]:
    names = subprocess.run(["git", "ls-files", "*.md"], cwd=root, capture_output=True, text=True, check=True).stdout
    return [root / n for n in names.split() if not n.startswith(SKIP)]


def stale(root: Path) -> list[str]:
    """The docs whose contents are missing, out of date, or there though the doc is short."""
    out = []
    for path in _docs(root):
        text = path.read_text(encoding="utf-8")
        want = with_toc(text) if wants_toc(text) else _BLOCK.sub("", text)
        if want != text:
            out.append(str(path.relative_to(root)))
    return out


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    if "--check" in argv:
        bad = stale(root)
        for name in bad:
            print(f"contents out of date: {name}")
        return 1 if bad else 0
    for name in stale(root):
        path = root / name
        text = path.read_text(encoding="utf-8")
        path.write_text(with_toc(text) if wants_toc(text) else _BLOCK.sub("", text), encoding="utf-8")
        print(f"wrote contents: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
