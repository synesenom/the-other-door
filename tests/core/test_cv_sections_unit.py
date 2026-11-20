import pytest

from door.core import cv_sections


@pytest.mark.parametrize("line, title", [
    ("## Technical Skills <!-- kind: skills -->", "Technical Skills"),
    ("## Kompetencer og værktøjer  <!--kind:skills-->", "Kompetencer og værktøjer"),
    ("## **Skills:** <!-- kind: skills -->", "Skills"),
    ("## Skills", "Skills"),
    ("## Selected work <!-- kind: nonsense -->", "Selected work"),
    ("## Selected work <!-- a note -->", "Selected work <!-- a note -->"),
])
def test_heading_is_the_title_without_a_kind_marker(line, title):
    assert cv_sections.heading(line) == title
