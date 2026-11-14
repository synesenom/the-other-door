"""A folder this build creates carries its data version from its first file (#56): the version file is authoritative."""

import pytest

from door.core import migrations, workspace

PROFILE = "0.1\n"
JOBS = "0.0\n"


@pytest.fixture
def home(tmp_path, monkeypatch):
    profile, jobs = tmp_path / "profile", tmp_path / "jobs"
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs)
    monkeypatch.setattr(workspace, "BACKUPS_DIR", tmp_path / "backups")
    return profile, jobs


def _stamped(folder, text):
    assert (folder / ".data_version").read_text() == text


def test_the_ledger_lock_stamps_a_jobs_folder_it_creates(home):
    from door.core import lock

    _, jobs = home
    with lock.ledger_lock(jobs, "set_status"):
        pass
    _stamped(jobs, JOBS)


def test_a_ledger_writing_core_stamps_jobs(home):
    from door.commands import status as status_cmd

    _, jobs = home
    status_cmd._mark_reviewed_core(jobs)
    _stamped(jobs, JOBS)


def test_init_stamps_the_profile(home):
    from door.commands import profile as profile_cmd

    profile, _ = home
    profile_cmd._init_core({"name": "Ada", "email": "a@x.com", "location": "Copenhagen", "role_targets": ["analyst"]})
    _stamped(profile, PROFILE)


def test_save_cv_stamps_the_profile_it_creates(home):
    from door.commands import profile as profile_cmd

    profile, _ = home
    profile_cmd._save_cv_core("# Ada\n")
    _stamped(profile, PROFILE)


def test_add_company_stamps_the_profile_it_creates(home):
    from door.commands import companies as companies_cmd

    profile, _ = home
    companies_cmd._add_core(["Acme"], probe=False)
    _stamped(profile, PROFILE)


def test_save_story_stamps_the_profile_it_creates(home):
    from door.commands import stories as stories_cmd

    profile, _ = home
    stories_cmd._save_story_core("A story", "c", "a", "r", "l")
    _stamped(profile, PROFILE)


def test_save_photo_stamps_the_profile_it_creates(home, tmp_path):
    import io

    from PIL import Image

    from door.core import photo

    profile, _ = home
    source = tmp_path / "me.jpg"
    buf = io.BytesIO()
    Image.new("RGB", (400, 500), (200, 120, 40)).save(buf, "JPEG")
    source.write_bytes(buf.getvalue())
    photo.save(source, profile)
    _stamped(profile, PROFILE)


def test_a_folder_with_v0_1_0_data_and_no_file_is_not_stamped_by_a_writer(home):
    from door.commands import stories as stories_cmd

    profile, _ = home
    profile.mkdir()
    (profile / "config.json").write_text("{}")
    stories_cmd._save_story_core("A story", "c", "a", "r", "l")
    assert not (profile / ".data_version").exists()
    assert migrations.read_version(profile) is None
