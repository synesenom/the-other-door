"""Unit tests for src/door/core/profile_loader.py (C2).

Covers Profile validation (role_targets/min_score/languages
rules), relative-path resolution against the project root, path-existence
checks, and load_profile's default-path + missing-file branches.
Pure and offline — filesystem only (tmp_path), no network.
"""

import json

import pytest
from pydantic import ValidationError

import door.core.profile_loader as profile_loader
from door.core import workspace
from door.core.profile_loader import Profile, load_profile


def _make_templates(dir_path):
    """Create the three template files load_profile requires; return their paths."""
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
# load_profile entry point
# --------------------------------------------------------------------------- #

def test_load_profile_reads_json(tmp_path):
    cfg = _valid_config(tmp_path / "tpl")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg))

    profile = load_profile(config_path)
    assert profile.name == "Jane Doe"


def test_load_profile_missing_file_raises(tmp_path):
    missing = tmp_path / "nope" / "config.json"
    with pytest.raises(FileNotFoundError, match="Copy profile.example"):
        load_profile(missing)


def test_load_profile_default_path(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "profile")
    cfg = _valid_config(tmp_path / "tpl")
    config_path = tmp_path / "profile" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(cfg))

    profile = load_profile()  # config_path=None -> workspace.PROFILE_DIR/config.json
    assert profile.email == "jane@example.com"


# --------------------------------------------------------------------------- #
# Complete schema: every key the code reads is declared (issue #137)
# --------------------------------------------------------------------------- #

def test_languages_accept_supported_names_and_codes(tmp_path):
    profile = Profile.model_validate(_valid_config(tmp_path / "tpl", languages=["English", "da"]))
    assert profile.languages == ["English", "da"]


@pytest.mark.parametrize("bad", ["Danish (B1)"])
def test_languages_reject_an_unsupported_entry_naming_the_supported_ones(tmp_path, bad):
    """Levels belong in the CV; `languages` lists the ad languages to consider."""
    with pytest.raises(ValidationError) as exc:
        Profile.model_validate(_valid_config(tmp_path / "tpl", languages=["English", bad]))
    message = str(exc.value)
    assert repr(bad) in message
    assert "English" in message and "Danish" in message


def test_unknown_top_level_key_fails_naming_the_key(tmp_path):
    with pytest.raises(ValidationError) as exc:
        Profile.model_validate(_valid_config(tmp_path / "tpl", greenhouse_board=["acme"]))
    assert any(err["loc"] == ("greenhouse_board",) for err in exc.value.errors())


def test_example_profile_validates_against_the_schema():
    """profile.example/config.json must use only declared keys (paths aside)."""
    example = json.loads(
        (profile_loader._PROJECT_ROOT / "profile.example" / "config.json").read_text()
    )
    unknown = set(example) - set(Profile.model_fields)
    assert unknown == set()


# --------------------------------------------------------------------------- #
# load_config: validate once, hand callers a plain dict (issue #137)
# --------------------------------------------------------------------------- #

def test_load_config_returns_only_the_keys_that_were_set(tmp_path):
    cfg = _valid_config(tmp_path / "tpl", max_age_days=14)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))

    config = profile_loader.load_config(path)

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
        profile_loader.load_config(path)

    lines = exc.value.lines
    assert any(line.startswith(f"{path}: min_sore — ") for line in lines)
    assert any(line.startswith(f"{path}: min_score — ") for line in lines)
    assert str(exc.value) == "\n".join(lines)


def test_load_config_reports_malformed_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    with pytest.raises(profile_loader.ConfigError) as exc:
        profile_loader.load_config(path)
    assert "invalid JSON" in str(exc.value)


def test_load_config_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        profile_loader.load_config(tmp_path / "nope.json")


def test_load_config_does_not_require_template_files(tmp_path):
    """Batch commands (scrape/match/run/list) never read the LaTeX
    templates, so a missing one must not stop them (#137 review)."""
    cfg = _valid_config(tmp_path / "tpl", cv_template=str(tmp_path / "gone.tex"))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    assert profile_loader.load_config(path)["cv_template"].endswith("gone.tex")


def test_load_config_check_paths_reports_missing_templates(tmp_path):
    cfg = _valid_config(tmp_path / "tpl", cv_template=str(tmp_path / "gone.tex"))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    with pytest.raises(profile_loader.ConfigError) as exc:
        profile_loader.load_config(path, check_paths=True)
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
