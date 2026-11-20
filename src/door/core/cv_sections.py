"""A cv.md's `## ` sections: the one reader of a section heading.

The kind of a section is read by `core/cv_read` (one model call over the CV), not from its title. An older cv.md may
still carry a `<!-- kind: ... -->` marker on a heading: it is only stripped from the title, nothing reads it as a kind.
"""

import re

_HEADING = re.compile(r"^##\s+(.*?)\s*(?:<!--\s*kind:\s*[a-z]+\s*-->)?\s*$")


def heading(line: str) -> str:
    """The title of a `## ` heading line: without a `<!-- kind: -->` marker of an older cv.md and without its `*`, `_`
    marks and colon."""
    return _HEADING.match(line).group(1).strip(" *_:")


def split(cv_md: str) -> list[list[str]]:
    """The CV's lines in sections, in order: each starts with its `## ` heading line, the first holds whatever
    comes before the first heading."""
    sections: list[list[str]] = [[]]
    for line in (cv_md or "").splitlines():
        if line.startswith("## "):
            sections.append([])
        sections[-1].append(line)
    return sections
