"""A cv.md's `## ` sections and their kinds: the one reader of a section heading.

The kind of a section is read by `core/cv_read` (one model call over the CV), not from its title. An older cv.md may
still carry a `<!-- kind: ... -->` marker on a heading: it is only stripped from the title, nothing reads it as a kind.
"""

import re

from door.core import cv_read

_HEADING = re.compile(r"^##\s+(.*?)\s*(?:<!--\s*kind:\s*([a-z]+)\s*-->)?\s*$")


KINDS = cv_read.COLUMN_KINDS


def heading(line: str) -> tuple[str, str | None]:
    """`(title, marker kind)` of a `## ` heading line: the title without a `<!-- kind: -->` marker of an older cv.md and
    without its `*`, `_` marks and colon. The kind is only what that marker names, None without one: no caller uses it,
    `core/cv_read` gives a section's kind."""
    title, kind = _HEADING.match(line).groups()
    return title.strip(" *_:"), kind if kind in KINDS else None


def split(cv_md: str) -> list[list[str]]:
    """The CV's lines in sections, in order: each starts with its `## ` heading line, the first holds whatever
    comes before the first heading."""
    sections: list[list[str]] = [[]]
    for line in (cv_md or "").splitlines():
        if line.startswith("## "):
            sections.append([])
        sections[-1].append(line)
    return sections
