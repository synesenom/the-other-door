"""A cv.md's `## ` sections and their kinds: the one reader of a section heading.

The model that drafts a CV records each section's kind on its heading line, `## Technical Skills <!-- kind: skills -->`
(one of the kinds a template's column can hold, whatever the title), so a reader needs no guess at a title written in
the user's own words; a heading with no marker has no kind here (`cv_read` reads it). The marker is a comment: no
renderer shows it.
"""

import re

from door.core import cv_read

_HEADING = re.compile(r"^##\s+(.*?)\s*(?:<!--\s*kind:\s*([a-z]+)\s*-->)?\s*$")


KINDS = cv_read.COLUMN_KINDS


def heading(line: str) -> tuple[str, str | None]:
    """`(title, recorded kind)` of a `## ` heading line: the title without the marker and its `*`, `_` marks and colon,
    the kind None without a marker or with one that is no section kind."""
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
