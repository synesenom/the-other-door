"""Unit tests for src/door/core/profile_loader.py (C2).

Covers Profile validation (role_targets/min_score/languages
rules), relative-path resolution against the project root, path-existence
checks.
Pure and offline — filesystem only (tmp_path), no network.
"""

import json

import pytest
from pydantic import ValidationError

import door.core.profile_loader as profile_loader
from door.core import workspace
from door.core.profile_loader import Profile


@pytest.fixture(autouse=True)
def _profile_folder(tmp_path, monkeypatch):
    """The files these tests name live under tmp_path: that is the profile folder."""
    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path)


def _make_templates(dir_path):
    """Create the three template files the loader requires; return their paths."""
    dir_path.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name in ("cv_template", "cv_content", "cover_letter_template"):
        p = dir_path / f"{name}.txt"
        p.write_text("x")
        paths[name] = p
    return paths


def _valid_config(template_dir, **overrides):
    """A valid config dict with absolute template paths; override per test."""
    files = _make_templates(template_dir)
    cfg = {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "location": "Copenhagen, Denmark",
        "cv_template": str(files["cv_template"]),
        "cv_content": str(files["cv_content"]),
        "cover_letter_template": str(files["cover_letter_template"]),
        "role_targets": ["Lead Data Scientist"],
        "remote": "hybrid",
    }
    cfg.update(overrides)
    return cfg


# --------------------------------------------------------------------------- #
# Happy path + defaults
# --------------------------------------------------------------------------- #

def test_valid_profile_and_defaults(tmp_path):
    profile = Profile.model_validate(_valid_config(tmp_path / "tpl"))

    assert profile.name == "Jane Doe"
    assert profile.remote == "hybrid"
    # Optional fields fall back to documented defaults.
    assert profile.min_score == 0.65
    assert profile.exclude.companies == []
    assert profile.exclude.keywords == []
    assert profile.languages == []


ACCENTS = ["none", "navy", "blue", "teal", "forest", "burgundy", "plum", "slate", "rust"]
FONTS = ["door", "editorial", "friendly", "plain"]


def test_the_cv_style_defaults_to_todays_look(tmp_path):
    profile = Profile.model_validate(_valid_config(tmp_path / "tpl"))
    assert (profile.cv_accent, profile.cv_fonts) == ("blue", "door")


@pytest.mark.parametrize("name", ACCENTS)
def test_every_accent_name_is_accepted(tmp_path, name):
    assert Profile.model_validate(_valid_config(tmp_path / "tpl", cv_accent=name)).cv_accent == name


@pytest.mark.parametrize("name", FONTS)
def test_every_font_pair_name_is_accepted(tmp_path, name):
    assert Profile.model_validate(_valid_config(tmp_path / "tpl", cv_fonts=name)).cv_fonts == name


@pytest.mark.parametrize("key,bad", [("cv_accent", "red"), ("cv_accent", "#fff"), ("cv_fonts", "Comic")])
def test_a_style_outside_the_lists_is_rejected(tmp_path, key, bad):
    with pytest.raises(ValidationError):
        Profile.model_validate(_valid_config(tmp_path / "tpl", **{key: bad}))


# --------------------------------------------------------------------------- #
# Field validation rules
# --------------------------------------------------------------------------- #

def test_empty_role_targets_rejected(tmp_path):
    cfg = _valid_config(tmp_path / "tpl", role_targets=[])
    with pytest.raises(ValidationError, match="role_targets must contain at least one"):
        Profile.model_validate(cfg)


@pytest.mark.parametrize("bad_score", [-0.1, 1.5])
def test_min_score_out_of_range_rejected(tmp_path, bad_score):
    cfg = _valid_config(tmp_path / "tpl", min_score=bad_score)
    with pytest.raises(ValidationError, match="min_score must be between 0.0 and 1.0"):
        Profile.model_validate(cfg)


@pytest.mark.parametrize("score", [0.0, 1.0])
def test_min_score_boundaries_accepted(tmp_path, score):
    cfg = _valid_config(tmp_path / f"tpl{score}", min_score=score)
    assert Profile.model_validate(cfg).min_score == score


def test_linkedin_discovery_is_off_by_default_and_can_be_turned_on(tmp_path):
    assert Profile.model_validate(_valid_config(tmp_path / "a")).linkedin_discovery is False
    assert Profile.model_validate(_valid_config(tmp_path / "b", linkedin_discovery=True)).linkedin_discovery is True


def test_profession_discovery_is_off_by_default_and_can_be_turned_on(tmp_path):
    assert Profile.model_validate(_valid_config(tmp_path / "a")).profession_discovery is False
    assert Profile.model_validate(_valid_config(tmp_path / "b", profession_discovery=True)).profession_discovery is True


def test_an_unregistered_source_discovery_key_is_refused(tmp_path):
    with pytest.raises(ValidationError):
        Profile.model_validate(_valid_config(tmp_path / "a", nowhere_discovery=True))


# --------------------------------------------------------------------------- #
# Path resolution + existence
# --------------------------------------------------------------------------- #

def test_topic_terms_are_optional(tmp_path):
    assert Profile.model_validate(_valid_config(tmp_path / "a")).topic_terms == []
    assert Profile.model_validate(_valid_config(tmp_path / "b", topic_terms=["data", "adat*"])).topic_terms == ["data", "adat*"]


def test_preferences_is_optional_free_text(tmp_path):
    assert Profile.model_validate(_valid_config(tmp_path / "a")).preferences == ""
    text = "medical or green energy; avoid banking"
    assert Profile.model_validate(_valid_config(tmp_path / "b", preferences=text)).preferences == text


def test_absolute_paths_kept_as_is(tmp_path):
    cfg = _valid_config(tmp_path / "tpl")
    profile = Profile.model_validate(cfg)
    assert profile.cv_template.is_absolute()
    assert str(profile.cv_template) == cfg["cv_template"]


def test_relative_paths_resolved_against_the_data_home(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    _make_templates(tmp_path / "assets")

    cfg = _valid_config(tmp_path / "throwaway")  # overwrite path fields below
    cfg["cv_template"] = "assets/cv_template.txt"
    cfg["cv_content"] = "assets/cv_content.txt"
    cfg["cover_letter_template"] = "assets/cover_letter_template.txt"

    profile = Profile.model_validate(cfg)

    assert profile.cv_template.is_absolute()
    assert profile.cv_template == (tmp_path / "assets" / "cv_template.txt").resolve()
    assert profile.cv_content.exists()


def test_missing_template_file_rejected(tmp_path):
    cfg = _valid_config(tmp_path / "tpl")
    cfg["cv_template"] = str(tmp_path / "does-not-exist.txt")
    with pytest.raises(ValidationError, match="cv_template not found"):
        Profile.model_validate(cfg)


def test_a_profile_with_no_cv_yet_is_valid(tmp_path):
    """No CV is "no CV yet" (the app's sidebar line), not a broken profile: its details can still be saved."""
    cfg = _valid_config(tmp_path / "tpl")
    cfg["cv_content"] = str(tmp_path / "cv.md")
    assert Profile.model_validate(cfg).cv_content == tmp_path / "cv.md"


# --------------------------------------------------------------------------- #
# load_profile_config: validate once, hand callers a plain dict (issue #137)
# --------------------------------------------------------------------------- #

def test_load_config_returns_only_the_keys_that_were_set(tmp_path):
    cfg = _valid_config(tmp_path / "tpl", max_age_days=14)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))

    config = profile_loader.load_profile_config(path.parent)

    assert isinstance(config, dict)
    assert config["max_age_days"] == 14
    # Unset optional keys stay absent so `config.get(key, default)` keeps
    # the caller's default (e.g. revise_model falls back to sonnet).
    assert "revise_model" not in config


def test_load_config_raises_config_error_with_one_line_per_problem(tmp_path):
    cfg = _valid_config(tmp_path / "tpl", min_sore=0.5, min_score=2)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))

    with pytest.raises(profile_loader.ConfigError) as exc:
        profile_loader.load_profile_config(path.parent)

    lines = exc.value.lines
    assert any(line.startswith(f"{path}: min_sore — ") for line in lines)
    assert any(line.startswith(f"{path}: min_score — ") for line in lines)
    assert str(exc.value) == "\n".join(lines)


def test_load_config_reports_malformed_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    with pytest.raises(profile_loader.ConfigError) as exc:
        profile_loader.load_profile_config(path.parent)
    assert "invalid JSON" in str(exc.value)


def test_load_config_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        profile_loader.load_profile_config(tmp_path / "nope")


def test_load_config_does_not_require_template_files(tmp_path):
    """Batch commands (scrape/match/run/list) never read the HTML
    templates, so a missing one must not stop them (#137 review)."""
    cfg = _valid_config(tmp_path / "tpl", cv_template=str(tmp_path / "gone.html"))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    assert profile_loader.load_profile_config(path.parent)["cv_template"].endswith("gone.html")


def test_load_config_check_paths_reports_missing_templates(tmp_path):
    cfg = _valid_config(tmp_path / "tpl", cv_template=str(tmp_path / "gone.html"))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    with pytest.raises(profile_loader.ConfigError) as exc:
        profile_loader.load_profile_config(path.parent, check_paths=True)
    assert any("cv_template not found" in line for line in exc.value.lines)


def test_needs_work_permit_defaults_to_false_and_loads_true(tmp_path):
    assert Profile.model_validate(_valid_config(tmp_path / "a")).needs_work_permit is False
    assert Profile.model_validate(_valid_config(tmp_path / "b", needs_work_permit=True)).needs_work_permit is True
    with pytest.raises(ValidationError):
        Profile.model_validate(_valid_config(tmp_path / "c", needs_work_permit="maybe"))


# --------------------------------------------------------------------------- #
# photo (#605)
# --------------------------------------------------------------------------- #

def _write_photo(path, data=None):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (400, 500), "grey").save(buf, "JPEG")
    path.write_bytes(buf.getvalue() if data is None else data)
    return path


def test_photo_is_optional_and_resolved_like_the_templates(tmp_path, monkeypatch):
    assert Profile.model_validate(_valid_config(tmp_path / "tpl")).photo is None
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    (tmp_path / "profile").mkdir()
    _write_photo(tmp_path / "profile" / "photo.jpg")
    profile = Profile.model_validate(_valid_config(tmp_path / "tpl", photo="profile/photo.jpg"))
    assert profile.photo == (tmp_path / "profile" / "photo.jpg").resolve()


def test_a_photo_that_is_missing_or_not_a_picture_is_refused_under_its_key(tmp_path):
    with pytest.raises(ValidationError, match="photo"):
        Profile.model_validate(_valid_config(tmp_path / "tpl", photo=str(tmp_path / "nope.jpg")))
    (tmp_path / "a.jpg").write_bytes(b"GIF89a")
    with pytest.raises(ValidationError, match="JPEG or PNG"):
        Profile.model_validate(_valid_config(tmp_path / "tpl", photo=str(tmp_path / "a.jpg")))


def test_a_missing_photo_does_not_stop_a_batch_command(tmp_path):
    cfg = _valid_config(tmp_path / "tpl", photo=str(tmp_path / "nope.jpg"))
    assert Profile.model_validate(cfg, context={"check_paths": False}).photo == tmp_path / "nope.jpg"


def test_the_templates_are_optional_and_a_profile_without_them_is_valid(tmp_path):
    """The templates come from the code (#56): no key, no file, no error, even with the paths checked."""
    cfg = _valid_config(tmp_path / "tpl")
    del cfg["cv_template"], cfg["cover_letter_template"]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    config = profile_loader.load_profile_config(path.parent, check_paths=True)
    assert "cv_template" not in config and "cover_letter_template" not in config


@pytest.mark.parametrize("key", ["cv_content", "cv_template", "cover_letter_template", "photo"])
@pytest.mark.parametrize("value", ["/Users/x/.config/door/drive.json", "../.config/door/drive.json"])
def test_a_cv_content_outside_the_profile_folder_is_refused_by_name(tmp_path, monkeypatch, key, value):
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "profile")
    cfg = _valid_config(tmp_path / "profile" / "tpl")
    cfg[key] = value
    with pytest.raises(ValidationError, match=f"{key} must be a file inside the profile folder"):
        Profile.model_validate(cfg)


def test_a_path_inside_the_profile_folder_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "profile")
    cfg = _valid_config(tmp_path / "profile" / "tpl")
    cfg["cv_content"] = "profile/cv.md"
    assert Profile.model_validate(cfg).cv_content == (tmp_path / "profile" / "cv.md").resolve()
