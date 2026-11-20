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


def test_the_kinds_are_the_ones_a_column_can_hold():
    assert cv_sections.KINDS == ("skills", "education", "certifications", "languages", "interests")
