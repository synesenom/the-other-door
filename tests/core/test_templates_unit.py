"""The HTML templates come from the code unless the user keeps their own (#56, #146)."""

import hashlib
import re

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
    "cv_template": "1388842149a1476be99ae15c38ddb3676de4d7977d08e67394ed22a8e954d007",
    "cover_letter_template": "014ae9272567bfc606efb35f8a936057b5e8f3b3c678c40ccba0c2623b578d42",
}


def test_the_shipped_templates_are_pinned():
    for key, name in templates.FILES.items():
        digest = hashlib.sha256((REPO_ROOT / "profile.example" / name).read_text(encoding="utf-8")
                                .replace("\r\n", "\n").encode()).hexdigest()
        assert digest == SHIPPED_HASHES[key], f"{name} changed: if that is meant, update its hash (now {digest})"


# --- the CV style: an accent colour and a font pair (#465) ---------------------------------------------------------

def test_the_defaults_add_no_style_at_all():
    """The templates' own CSS is the default look: the app's blue headings and rule, the door fonts."""
    assert templates.style_css({}) == ""
    assert templates.style_css({"cv_accent": "blue", "cv_fonts": "door"}) == ""


def test_no_colour_is_ink_headings_and_a_hairline_rule():
    css = templates.style_css({"cv_accent": "none"})
    assert "--heading:#1E1A16" in css and "--rule:#D6C7A8" in css


def test_blue_is_the_apps_blue():
    assert templates.ACCENTS["blue"] == "#2f55c8"


def test_an_accent_colours_the_headings_and_the_rule():
    css = templates.style_css({"cv_accent": "navy"})
    assert "--heading:#1f3a5f" in css and "--rule:#1f3a5f" in css and css.startswith(":root{")


def test_a_font_pair_names_its_two_families():
    css = templates.style_css({"cv_fonts": "editorial"})
    assert "Playfair Display" in css and "Lato" in css


def test_an_unknown_value_falls_back_and_is_never_echoed():
    assert templates.style_css({"cv_accent": "red; } body { display:none", "cv_fonts": "Comic"}) == ""  # the defaults
    assert templates.style_css({"cv_accent": 3, "cv_fonts": None}) == ""


def test_every_font_a_template_loads_is_a_shipped_truetype_file():
    shipped = REPO_ROOT / "profile.example" / "fonts"
    for template in ("cv.template.html", "cover-letter.template.html"):
        text = (REPO_ROOT / "profile.example" / template).read_text()
        for name in re.findall(r"/fonts/([\w.-]+\.ttf)", text):
            assert (shipped / name).is_file(), f"{template}: {name}"
            assert (shipped / f"{name.split('-')[0]}-OFL.txt").is_file(), f"{template}: the licence of {name}"


def test_the_apps_swatches_are_the_accent_table():
    import json
    swatches = json.loads((REPO_ROOT / "app/src/renderer/screens/profile-form/cv-style.json").read_text())["colours"]
    assert {k: v[1] for k, v in swatches.items() if k != "none"} == templates.ACCENTS
