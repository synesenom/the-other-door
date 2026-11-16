"""The HTML templates come from the code unless the user keeps their own (#56, #146)."""

import hashlib

import pytest

from door.core import templates, workspace
from paths import REPO_ROOT


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    profile, example = tmp_path / "profile", tmp_path / "profile.example"
    profile.mkdir()
    example.mkdir()
    (example / "cv.template.html").write_text("code cv")
    (example / "cover-letter.template.html").write_text("code letter")
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "PROFILE_EXAMPLE_DIR", example)
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    return profile, example


def test_the_templates_are_html_files():
    assert templates.FILES == {"cv_template": "cv.template.html", "cover_letter_template": "cover-letter.template.html"}


def test_the_code_template_is_used_when_the_user_has_none(dirs):
    _, example = dirs
    assert templates.resolve("cv_template") == example / "cv.template.html"
    assert templates.resolve("cover_letter_template") == example / "cover-letter.template.html"


def test_a_file_the_user_put_in_the_profile_wins(dirs):
    profile, _ = dirs
    (profile / "cv.template.html").write_text("mine")
    assert templates.resolve("cv_template") == profile / "cv.template.html"
    assert templates.resolve("cover_letter_template").parent != profile


def test_a_path_in_the_config_wins_over_both(dirs, tmp_path):
    profile, _ = dirs
    (profile / "cv.template.html").write_text("mine")
    own = tmp_path / "other" / "my.html"
    own.parent.mkdir()
    own.write_text("x")
    assert templates.resolve("cv_template", {"cv_template": str(own)}) == own


def test_a_relative_config_path_resolves_from_the_data_folder(dirs, tmp_path):
    own = tmp_path / "mine" / "cv.html"
    own.parent.mkdir()
    own.write_text("x")
    assert templates.resolve("cv_template", {"cv_template": "mine/cv.html"}) == own


def test_a_config_path_that_is_not_there_falls_back(dirs):
    _, example = dirs
    assert templates.resolve("cv_template", {"cv_template": "/nowhere/cv.html"}) == example / "cv.template.html"


def test_a_tex_template_is_not_read(dirs, tmp_path):
    """A LaTeX template cannot be printed by a browser: the shipped HTML one is used instead."""
    profile, example = dirs
    own = tmp_path / "mine.tex"
    own.write_text("\\documentclass{article}")
    (profile / "cv.template.tex").write_text("\\documentclass{article}")
    assert templates.resolve("cv_template", {"cv_template": str(own)}) == example / "cv.template.html"


def test_the_shipped_templates_carry_the_two_tokens_and_the_page():
    shipped = REPO_ROOT / "profile.example"
    for name in templates.FILES.values():
        text = (shipped / name).read_text(encoding="utf-8")
        assert text.count("<<body>>") == 1 and text.count('<html lang="<<lang>>">') == 1, name
        assert "@page" in text and "/fonts/Figtree-Regular.ttf" in text and "hyphens: manual" in text, name
        assert "<script" not in text and "@import" not in text and "http" not in text.replace("https://...", ""), name


# A pinned hash: a change to a shipped template is deliberate (a user's own copy does not follow it).
SHIPPED_HASHES = {
    "cv_template": "25cb26b026fe35f2d21c0d0b9d4a37b892d9a2e19adebec96b7720dc428c482e",
    "cover_letter_template": "2c917ca8f82bf1dd541c276a86eb4bde3049cd62161a8aa37e5d3871f1e1929f",
}


def test_the_shipped_templates_are_pinned():
    for key, name in templates.FILES.items():
        digest = hashlib.sha256((REPO_ROOT / "profile.example" / name).read_text(encoding="utf-8")
                                .replace("\r\n", "\n").encode()).hexdigest()
        assert digest == SHIPPED_HASHES[key], f"{name} changed: if that is meant, update its hash (now {digest})"
