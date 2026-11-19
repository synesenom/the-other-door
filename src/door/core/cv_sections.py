"""A cv.md's `## ` sections and their kinds: the one reader of a section heading.

The model that drafts a CV records each section's kind on its heading line, `## Technical Skills <!-- kind: skills -->`
(one of `i18n.CvSections`' kinds, whatever the title), so a reader needs no guess at a title written in the user's own
words. A heading with no marker is of the kind its whole title names (`i18n.cv_section_kind`: a hand-typed `## Skills`),
else of none. The marker is a comment: no renderer shows it.
"""

import re

from door import i18n

_HEADING = re.compile(r"^##\s+(.*?)\s*(?:<!--\s*kind:\s*([a-z]+)\s*-->)?\s*$")


KINDS = tuple(i18n.CvSections.model_fields)


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


def kind(section: list[str], kinds, codes: tuple[str, ...] | None = None) -> str | None:
    """The one of `kinds` the section is of: the kind recorded on its heading, else the kind its whole title names
    in the languages `codes` (None: all)."""
    head = section[0] if section else ""
    if not head.startswith("## "):
        return None
    title, recorded = heading(head)
    if recorded:
        return recorded if recorded in kinds else None
    return i18n.cv_section_kind(title, kinds, codes)
