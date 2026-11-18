"""The example CV template's photo slot and header (#605, #142, #146): the CSS a printed photo needs is there. What
prints is pinned on the real Chromium in `test_template_print.py`."""

import re

from paths import REPO_ROOT

_TEMPLATE = (REPO_ROOT / "profile.example" / "cv.template.html").read_text(encoding="utf-8")
_LETTER = (REPO_ROOT / "profile.example" / "cover-letter.template.html").read_text(encoding="utf-8")


def test_the_template_styles_the_photo_class_compile_looks_for():
    from door.render import page

    css = page._COMMENTS.sub("", _TEMPLATE)
    assert page._PHOTO_CLASS.search(css)
    assert re.search(r"\.cv-header \.photo\s*\{[^}]*width:\s*2\.2cm", css)


def test_a_header_with_a_photo_is_a_grid_and_one_without_is_a_dotted_line():
    assert ".cv-header:has(.photo)" in _TEMPLATE and "grid-template-columns" in _TEMPLATE
    assert re.search(r'\.contact span:not\(:last-child\)::after \{ content: "\\00B7"', _TEMPLATE)
    assert re.search(r"\.cv-header:has\(\.photo\) \.contact span \{ display: block", _TEMPLATE)


def test_the_page_and_the_type_are_set_by_the_template():
    for text in (_TEMPLATE, _LETTER):
        assert re.search(r"@page \{ size: A4; margin: 2\.2cm 2\.4cm 2cm 2\.4cm; \}", text)
        assert "hyphens: manual" in text and "font-synthesis: none" in text
        for colour in ("#1E1A16", "#6B6157", "#D6C7A8", "#2F55C8"):
            assert colour in text, colour


def test_the_template_itself_passes_no_script_and_reaches_nothing():
    for text in (_TEMPLATE, _LETTER):
        assert "<script" not in text and "@import" not in text and "javascript:" not in text
        assert not re.search(r"url\((?!/fonts/)", text), "only the fonts are loaded"
