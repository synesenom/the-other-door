import pytest

from door.core import cv_sections


@pytest.mark.parametrize("line, title, kind", [
    ("## Technical Skills <!-- kind: skills -->", "Technical Skills", "skills"),
    ("## Kompetencer og værktøjer  <!--kind:skills-->", "Kompetencer og værktøjer", "skills"),
    ("## **Skills:** <!-- kind: skills -->", "Skills", "skills"),
    ("## Skills", "Skills", None),
    ("## Selected work <!-- kind: nonsense -->", "Selected work", None),
    ("## Selected work <!-- a note -->", "Selected work <!-- a note -->", None),
])
def test_heading_reads_the_recorded_kind_and_strips_it_from_the_title(line, title, kind):
    assert cv_sections.heading(line) == (title, kind)


def test_kind_is_the_marker_else_a_whole_standard_title_else_none():
    kinds = ("skills", "education")
    assert cv_sections.kind(["## Tools I use <!-- kind: skills -->"], kinds) == "skills"
    assert cv_sections.kind(["## Skills"], kinds) == "skills"
    assert cv_sections.kind(["## Technical Skills"], kinds) == "skills"  # a standard title
    assert cv_sections.kind(["## Tools I use"], kinds) is None
    assert cv_sections.kind(["## Tools I use <!-- kind: education -->"], ("skills",)) is None
    assert cv_sections.kind(["# Jane", "text"], kinds) is None
