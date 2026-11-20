"""`cv_style_sample` (#465): the user's CV (else the example CV) printed in a chosen style, page 1 as a PNG."""

import base64
import io
import json

import pytest
from PIL import Image

from compile_utils import install
from door.commands import cv_style_sample as sample_cmd
from door.core import cv_read, workspace
from paths import REPO_ROOT

CV = "# Ada Lovelace\n\n**Email:** ada@example.com\n\n## Experience\n\n### Analyst, Engine Co 2020 - 2023\n- Wrote the first program\n"


@pytest.fixture
def world(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "cv.md").write_text(CV, encoding="utf-8")
    (profile / "config.json").write_text(json.dumps({"name": "Ada Lovelace", "location": "Copenhagen"}))
    example = tmp_path / "profile.example"
    (example / "fonts").mkdir(parents=True)
    (example / "cv.md").write_text("# Jane Doe\n\n## Experience\n\n### Analyst, Acme 2019 - 2021\n- Did things\n", encoding="utf-8")
    shipped = REPO_ROOT / "profile.example"
    (example / "cv.template.html").write_text((shipped / "cv.template.html").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "PROFILE_EXAMPLE_DIR", example)
    printed = install(monkeypatch)
    return type("World", (), {"print": printed, "profile": profile, "home": tmp_path})


def _png(result):
    return Image.open(io.BytesIO(base64.b64decode(result["png_base64"])))


def test_the_sample_is_a_png_of_the_users_cv_in_the_chosen_style(world):
    result = sample_cmd._cv_style_sample_core("burgundy", "friendly")
    assert _png(result).format == "PNG" and result["own_cv"] is True
    html = world.print.calls[0]["html"]
    assert "Ada Lovelace" in html and "#8a1c3c" in html and "Montserrat" in html


def test_without_a_cv_the_example_cv_is_printed(world):
    (world.profile / "cv.md").unlink()
    result = sample_cmd._cv_style_sample_core("none", "door")
    assert result["own_cv"] is False and "Jane Doe" in world.print.calls[0]["html"]
    assert "<style>:root{" not in world.print.calls[0]["html"]


def test_the_same_choice_is_answered_from_the_cache_and_another_accent_prints_again(world):
    first = sample_cmd._cv_style_sample_core("teal", "door")
    again = sample_cmd._cv_style_sample_core("teal", "door")
    assert len(world.print.calls) == 1 and again["png_base64"] == first["png_base64"]
    sample_cmd._cv_style_sample_core("rust", "door")
    assert len(world.print.calls) == 2


def test_a_changed_cv_prints_again(world):
    sample_cmd._cv_style_sample_core("teal", "door")
    (world.profile / "cv.md").write_text(CV + "- More\n", encoding="utf-8")
    sample_cmd._cv_style_sample_core("teal", "door")
    assert len(world.print.calls) == 2


def test_only_the_png_is_kept_in_the_cache_folder(world):
    sample_cmd._cv_style_sample_core("teal", "door")
    kept = sorted(p.name for p in (world.home / ".style" / "preview").iterdir())
    assert len(kept) == 1 and kept[0].endswith(".png")


def test_a_cv_that_cannot_be_read_is_an_error_in_words(world, monkeypatch):
    def fail(md):
        raise cv_read.CvReadError("Could not read your CV: try again.")
    monkeypatch.setattr(cv_read, "_ask", fail)
    assert sample_cmd._cv_style_sample_core("teal", "door") == {"error": "Could not read your CV: try again."}


@pytest.mark.parametrize("accent,fonts", [("red", "door"), ("none", "Comic")])
def test_a_choice_outside_the_lists_is_refused(world, accent, fonts):
    with pytest.raises(ValueError):
        sample_cmd._cv_style_sample_core(accent, fonts)


def test_a_failed_print_is_an_error_in_words(world, monkeypatch):
    install(monkeypatch, fail="Chromium crashed")
    assert "Chromium crashed" in sample_cmd._cv_style_sample_core("teal", "door")["error"]
