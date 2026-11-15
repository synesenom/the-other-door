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


# --- fixes of the shipped templates a user's own copy lacks (#156) ---

import hashlib  # noqa: E402

from door.core import doctor  # noqa: E402
from paths import REPO_ROOT  # noqa: E402

SHIPPED = REPO_ROOT / "profile.example"
OLD = REPO_ROOT / "tests" / "data_versions" / "0.1.0" / "profile"

# The hashes of the shipped templates; a change must be considered for FIXES.
SHIPPED_HASHES = {
    "cv_template": "b78ce3f0c21acffb3eb72f67766527aab184658bc255d4519fadbba1b2d25fb7",
    "cover_letter_template": "0ac1a210d2163f7e7175b649694f13e3065fb599e94b34f7962ee5c04e8aea02",
}


def _read(folder, key):
    return (folder / templates.FILES[key]).read_text(encoding="utf-8")


def test_every_fix_is_in_the_shipped_template_and_not_in_the_old_one():
    assert templates.FIXES
    for fix in templates.FIXES:
        assert fix["has"] in _read(SHIPPED, fix["template"]), fix
        assert fix["has"] not in _read(OLD, fix["template"]), fix


def test_missing_fixes_names_what_an_old_copy_lacks():
    old_cv = templates.missing_fixes("cv_template", _read(OLD, "cv_template"))
    assert {f["issue"] for f in old_cv} == {142, 143}
    old_letter = templates.missing_fixes("cover_letter_template", _read(OLD, "cover_letter_template"))
    assert {f["issue"] for f in old_letter} == {143}


def test_missing_fixes_is_empty_for_the_shipped_templates():
    for key in templates.FILES:
        assert templates.missing_fixes(key, _read(SHIPPED, key)) == []


def test_a_fix_that_does_not_apply_is_not_named():
    text = "\\documentclass{article}\n\\usepackage{hyperref}\n"
    assert {f["issue"] for f in templates.missing_fixes("cv_template", text)} == {143}


def test_the_shipped_templates_are_pinned():
    for key in templates.FILES:
        digest = hashlib.sha256(_read(SHIPPED, key).replace("\r\n", "\n").encode()).hexdigest()
        assert digest == SHIPPED_HASHES[key], (
            "the shipped template changed: add a FIXES entry if a user's copy needs the change, then update the hash"
        )


def test_doctor_says_nothing_when_no_template_is_the_users_own(dirs):
    profile, example = dirs
    assert doctor.check_templates({}, profile) is None


def test_doctor_is_ok_for_an_own_copy_with_every_fix(dirs):
    profile, example = dirs
    (profile / "cv.template.tex").write_text(_read(SHIPPED, "cv_template"))
    check = doctor.check_templates({}, profile)
    assert check["name"] == "templates" and check["status"] == "ok" and check["required"] is False
    assert "every fix" in check["detail"]


def test_doctor_warns_for_an_old_own_copy(dirs):
    profile, example = dirs
    (profile / "cv.template.tex").write_text(_read(OLD, "cv_template"))
    check = doctor.check_templates({}, profile)
    assert check["status"] == "warn"
    assert "lacks 2 fixes" in check["detail"]
    assert str(profile / "cv.template.tex") in check["detail"]
    assert "contact details on one line" in check["detail"]
    assert "no French space" in check["detail"]
    assert "\\newcommand*{\\cv@photo}" in check["fix"] and str(example / "cv.template.tex") in check["fix"]


def test_doctor_reads_a_template_the_config_names(dirs, tmp_path):
    profile, _ = dirs
    mine = tmp_path / "mine.tex"
    mine.write_text(_read(OLD, "cover_letter_template"))
    check = doctor.check_templates({"cover_letter_template": str(mine)}, profile)
    assert check["status"] == "warn" and "lacks 1 fix " in check["detail"]
