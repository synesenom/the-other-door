"""The LaTeX templates come from the code unless the user keeps their own (#56)."""

import pytest

from door.core import templates, workspace


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    profile, example = tmp_path / "profile", tmp_path / "profile.example"
    profile.mkdir()
    example.mkdir()
    (example / "cv.template.tex").write_text("code cv")
    (example / "cover-letter.template.tex").write_text("code letter")
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "PROFILE_EXAMPLE_DIR", example)
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    return profile, example


def test_the_code_template_is_used_when_the_user_has_none(dirs):
    _, example = dirs
    assert templates.resolve("cv_template") == example / "cv.template.tex"
    assert templates.resolve("cover_letter_template") == example / "cover-letter.template.tex"


def test_a_file_the_user_put_in_the_profile_wins(dirs):
    profile, _ = dirs
    (profile / "cv.template.tex").write_text("mine")
    assert templates.resolve("cv_template") == profile / "cv.template.tex"
    assert templates.resolve("cover_letter_template").parent != profile


def test_a_path_in_the_config_wins_over_both(dirs, tmp_path):
    profile, _ = dirs
    (profile / "cv.template.tex").write_text("mine")
    own = tmp_path / "other" / "my.tex"
    own.parent.mkdir()
    own.write_text("x")
    assert templates.resolve("cv_template", {"cv_template": str(own)}) == own


def test_a_relative_config_path_resolves_from_the_data_folder(dirs, tmp_path):
    own = tmp_path / "mine" / "cv.tex"
    own.parent.mkdir()
    own.write_text("x")
    assert templates.resolve("cv_template", {"cv_template": "mine/cv.tex"}) == own


def test_a_config_path_that_is_not_there_falls_back(dirs):
    _, example = dirs
    assert templates.resolve("cv_template", {"cv_template": "/nowhere/cv.tex"}) == example / "cv.template.tex"
