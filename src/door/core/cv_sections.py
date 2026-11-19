"""A cv.md's `## ` sections, read by kind: the one reader the skill terms, the draft's TODO clean-up and the
experience count call, so a section the user titled in their own words is found as the standard ones are."""

from door import i18n


def split(cv_md: str) -> list[list[str]]:
    """The CV's lines in sections, in order: each starts with its `## ` heading line, the first holds whatever
    comes before the first heading."""
    sections: list[list[str]] = [[]]
    for line in (cv_md or "").splitlines():
        if line.startswith("## "):
            sections.append([])
        sections[-1].append(line)
    return sections


def kind(section: list[str], kinds) -> str | None:
    """The one of `kinds` the section's heading is about, or None (`i18n.cv_heading_kind`)."""
    head = section[0] if section else ""
    return i18n.cv_heading_kind(head[3:].strip(" *_"), kinds) if head.startswith("## ") else None
