"""The example CV is Jane Doe's: nothing is scored or tailored against it."""

import json
import shutil

import pytest

from door.commands import find as find_cmd
from door.commands import match as match_cmd
from door.commands import prepare as prepare_cmd
from door.commands import scrape as scrape_cmd
from door.core import workspace
from door.core.profile_loader import ConfigError


@pytest.fixture
def example_cv(cli_env):
    cv = cli_env.profile_dir / "cv.md"
    shutil.copy2(workspace.PROFILE_EXAMPLE_DIR / "cv.md", cv)
    config = cli_env.profile_dir / "config.json"
    config.write_text(json.dumps({**json.loads(config.read_text()), "cv_content": str(cv)}))
    return cli_env


def test_match_refuses_the_example_cv(example_cv):
    with pytest.raises(ConfigError, match="example"):
        match_cmd._match_core(jobs_dir=example_cv.jobs_dir, profile_dir=example_cv.profile_dir)


def test_a_run_that_scores_refuses_before_it_reads_anything(example_cv, monkeypatch):
    def no_network(*_args, **_kwargs):
        raise AssertionError("the run started")

    monkeypatch.setattr(scrape_cmd, "_scrape_core", no_network)
    with pytest.raises(ConfigError, match="example"):
        find_cmd._find_core(jobs_dir=example_cv.jobs_dir, profile_dir=example_cv.profile_dir)
    with pytest.raises(ConfigError, match="example"):
        find_cmd._find_core("match", jobs_dir=example_cv.jobs_dir, profile_dir=example_cv.profile_dir)


def test_prepare_fails_on_the_example_cv(example_cv):
    result = prepare_cmd._prepare_core("jobindex.1", jobs_dir=example_cv.jobs_dir, profile_dir=example_cv.profile_dir)
    assert result["outcome"] == "failed"
    assert "example" in result["error"]


def test_a_changed_cv_is_the_users_own(example_cv):
    from door.commands import _common as common

    cv = example_cv.profile_dir / "cv.md"
    assert common._cv_is_example({}, example_cv.profile_dir)
    cv.write_text(cv.read_text() + "\nOne more line.\n")
    assert not common._cv_is_example({}, example_cv.profile_dir)


def test_a_cv_named_by_a_relative_path_is_found_from_the_data_folder(example_cv, monkeypatch, tmp_path):
    from door.commands import _common as common

    monkeypatch.setattr(workspace, "HOME", tmp_path)
    (tmp_path / "elsewhere").mkdir()
    shutil.copy2(workspace.PROFILE_EXAMPLE_DIR / "cv.md", tmp_path / "elsewhere" / "cv.md")
    (example_cv.profile_dir / "cv.md").write_text("# My own\n")
    config = {"cv_content": "elsewhere/cv.md"}
    assert common._cv_is_example(config, example_cv.profile_dir)
    (tmp_path / "elsewhere" / "cv.md").write_text("# Someone real\n")
    assert not common._cv_is_example(config, example_cv.profile_dir)


def test_no_cv_at_all_is_not_the_example(example_cv):
    from door.commands import _common as common

    (example_cv.profile_dir / "cv.md").unlink()
    assert not common._cv_is_example({}, example_cv.profile_dir)


# --- an older copy of the example is still the example (#189) -----------------------------------------------

def test_the_example_as_it_was_before_the_header_extras_is_still_the_example(example_cv):
    from paths import TESTS_DIR
    from door.commands import _common as common

    saved = (TESTS_DIR / "commands" / "fixtures" / "example_cv_before_189.md").read_bytes()
    assert saved != (workspace.PROFILE_EXAMPLE_DIR / "cv.md").read_bytes()  # the example did change
    (example_cv.profile_dir / "cv.md").write_bytes(saved)
    assert common._cv_is_example({}, example_cv.profile_dir)
    with pytest.raises(ConfigError, match="example"):
        match_cmd._match_core(jobs_dir=example_cv.jobs_dir, profile_dir=example_cv.profile_dir)


def test_one_byte_off_either_version_is_not_the_example(example_cv):
    from paths import TESTS_DIR
    from door.commands import _common as common

    saved = (TESTS_DIR / "commands" / "fixtures" / "example_cv_before_189.md").read_bytes()
    for text in (saved + b" ", (workspace.PROFILE_EXAMPLE_DIR / "cv.md").read_bytes() + b" "):
        (example_cv.profile_dir / "cv.md").write_bytes(text)
        assert not common._cv_is_example({}, example_cv.profile_dir)


def test_every_past_example_is_in_the_list():
    """Add the old hash to `_PAST_EXAMPLE_CV_SHA256` whenever profile.example/cv.md changes."""
    import hashlib
    import subprocess

    from door.commands import _common as common
    from paths import REPO_ROOT

    log = subprocess.run(["git", "log", "--format=%H", "--", "profile.example/cv.md"], cwd=REPO_ROOT,
                         capture_output=True, text=True)
    if log.returncode != 0 or not log.stdout.split():
        pytest.skip("no git history here")
    for commit in log.stdout.split()[1:]:  # the newest is the current one, recognised by bytes
        shown = subprocess.run(["git", "show", f"{commit}:profile.example/cv.md"], cwd=REPO_ROOT, capture_output=True)
        if shown.returncode == 0:
            assert hashlib.sha256(shown.stdout).hexdigest() in common._PAST_EXAMPLE_CV_SHA256, commit
