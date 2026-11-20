"""template.json names what a template's folder lends it (#188)."""

import json

import pytest

from door.core import cv_read, templates


def _write(tmp_path, data):
    folder = tmp_path / "tpl"
    folder.mkdir(exist_ok=True)
    (folder / "template.json").write_text(data if isinstance(data, str) else json.dumps(data))
    return folder / "cv.template.html"


def test_no_manifest_is_none(tmp_path):
    assert templates.manifest(tmp_path / "cv.template.html") is None


def test_an_empty_manifest_gives_the_defaults(tmp_path):
    m = templates.manifest(_write(tmp_path, {}))
    assert (m.fonts, m.icons, m.max_pages, m.columns) == ([], {}, None, None)


def test_a_full_manifest_is_read(tmp_path):
    path = _write(tmp_path, {"version": 1, "fonts": ["A.ttf"], "icons": {"phone": "p.svg"}, "max_pages": 1,
                             "columns": {"side": ["skills"]}})
    m = templates.manifest(path)
    assert m.fonts == ["A.ttf"] and m.icons == {"phone": "p.svg"} and m.max_pages == 1
    assert m.columns.side == ["skills"]


def test_the_section_kinds_are_what_a_column_can_hold():
    assert {"skills", "education", "certifications", "languages", "interests"} == set(templates.SECTION_KINDS)
    assert templates.ICON_KINDS == (*cv_read.CONTACT_KINDS, "date")


@pytest.mark.parametrize("data", [
    {"colour": "red"},
    {"version": 2},
    {"fonts": ["A.otf"]},
    {"fonts": ["A.woff2"]},
    {"fonts": ["sub/A.ttf"]},
    {"fonts": ["../A.ttf"]},
    {"fonts": ["..\\A.ttf"]},
    {"icons": {"fax": "f.svg"}},
    {"icons": {"phone": "p.png"}},
    {"icons": {"phone": "../p.svg"}},
    {"columns": {"side": ["hobbies"]}},
    {"columns": {"main": ["skills"]}},
    {"max_pages": 0},
    {"max_pages": 4},
    "{not json",
    "[]",
])
def test_a_wrong_manifest_is_refused(tmp_path, data):
    with pytest.raises(ValueError):
        templates.manifest(_write(tmp_path, data))


def test_an_icon_kind_is_a_contact_kind_the_guard_lets_through_or_the_entry_date():
    from door.render import html_guard

    assert set(templates.ICON_KINDS) - {"date"} <= html_guard.CLASSES  # a kind the tailor may write is one a template may draw

