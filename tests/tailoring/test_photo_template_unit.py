"""The example CV template's photo slot (#605)."""

import re

from paths import REPO_ROOT

from door.tailoring import tex_guard

_TEMPLATE = (REPO_ROOT / "profile.example" / "cv.template.tex").read_text(encoding="utf-8")


def test_the_template_defines_the_photo_box_compile_looks_for():
    from door.commands import compile as compile_cmd

    assert compile_cmd._PHOTO_BOX.search(_TEMPLATE)
    assert "\\usepackage{graphicx}" in _TEMPLATE


def test_the_template_itself_passes_the_guard():
    # the one \includegraphics is compile's, put in after the guard has read the document
    assert tex_guard.unsafe(_TEMPLATE) == []


def test_the_photo_box_takes_one_argument_and_places_it_on_the_page():
    m = re.search(r"\\newcommand\{\\cvphotobox\}\[1\]\{", _TEMPLATE)
    assert m
