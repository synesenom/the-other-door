"""The previews of #207 with the real Chromium: the user's cv.md and the sample letter printed in the default template
and in a style, as page images. Marked `real_chromium` like test_style_build.py."""

import os
import shutil

import pytest
from PIL import Image

from door.core import chromium, workspace
from door.tailoring import style_preview
from paths import REPO_ROOT

pytestmark = [
    pytest.mark.real_chromium,
    pytest.mark.skipif(chromium.find_chromium() is None and not os.environ.get("CI"),
                       reason="no Chromium headless shell installed"),
]


def test_both_styles_are_printed_from_the_users_cv(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    (profile / "style").mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / "profile.example" / "cv.md", profile / "cv.md")
    for name in ("cv.template.html", "cover-letter.template.html"):
        shutil.copyfile(REPO_ROOT / "profile.example" / name, profile / "style" / name)
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    shown = style_preview.show(tmp_path, profile, {})
    assert list(shown["styles"]) == ["default", "like"]
    for style in shown["styles"].values():
        assert style["cv"] and style["letter"]
        for png in (*style["cv"], *style["letter"]):
            width, height = Image.open(png).size
            assert height > width > 500  # a portrait page at reading size
