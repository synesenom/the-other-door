"""template.json names what a template's folder lends it (#188)."""

import json

import pytest

from door import i18n
from door.core import templates


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


def test_the_section_kinds_are_the_cv_sections_and_two_more():
    assert set(templates.SECTION_KINDS) == set(i18n.CvSections.model_fields) | {"languages", "interests"}
    assert set(templates.ICON_KINDS) == {"phone", "email", "web", "location", "linkedin", "github", "date"}


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
