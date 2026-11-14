"""Drive sync decisions and dirty detection (issue #265)."""

import os

import pytest

from door.core import sync


@pytest.mark.parametrize(
    "remote, synced, dirty, has_local, expected",
    [
        (None, None, False, True, "push"),
        (None, "v1", False, True, "push"),
        (None, None, False, False, "nothing"),
        ("v1", "v1", False, True, "nothing"),
        ("v1", "v1", True, True, "push"),
        ("v2", "v1", False, True, "pull"),
        ("v2", "v1", True, True, "conflict"),
        ("v1", None, False, False, "pull"),
        ("v1", None, False, True, "conflict"),
    ],
)
def test_decide_table(remote, synced, dirty, has_local, expected):
    assert sync.decide(remote, synced, dirty, has_local_data=has_local) == expected


def _tree(tmp_path):
    profile, jobs = tmp_path / "profile", tmp_path / "jobs"
    profile.mkdir()
    jobs.mkdir()
    (profile / "config.json").write_text("{}")
    (jobs / "history.json").write_text("{}")
    return profile, jobs


def test_fingerprint_is_stable_and_sees_add_edit_remove(tmp_path):
    profile, jobs = _tree(tmp_path)
    base = sync.fingerprint(profile, jobs)
    assert sync.fingerprint(profile, jobs) == base
    (jobs / "new.json").write_text("x")
    added = sync.fingerprint(profile, jobs)
    assert added != base
    (jobs / "new.json").write_text("xyz")
    edited = sync.fingerprint(profile, jobs)
    assert edited != added
    (jobs / "new.json").unlink()
    assert sync.fingerprint(profile, jobs) == base


def test_fingerprint_sees_an_mtime_change(tmp_path):
    profile, jobs = _tree(tmp_path)
    base = sync.fingerprint(profile, jobs)
    os.utime(jobs / "history.json", ns=(1, 1))
    assert sync.fingerprint(profile, jobs) != base


def test_fingerprint_ignores_lock_and_progress_files(tmp_path):
    profile, jobs = _tree(tmp_path)
    base = sync.fingerprint(profile, jobs)
    for name in (".lock", ".lock.json", ".progress.json"):
        (jobs / name).write_text("x")
    assert sync.fingerprint(profile, jobs) == base


def test_fingerprint_with_missing_dirs(tmp_path):
    assert sync.fingerprint(tmp_path / "nope", tmp_path / "nada") == sync.fingerprint(tmp_path / "a", tmp_path / "b")


# --------------------------------------------------------------------------- pull / push / sync_now
import json
import shutil
from pathlib import Path

from door.core import drive


class FakeDrive:
    """Stands in for Google Drive: one blob and a version counter."""

    def __init__(self, monkeypatch, tmp_path):
        monkeypatch.setattr(drive, "_BASE", tmp_path / "cfg")
        drive.write_state({"refresh_token": "rt", "account": "me@x.org"})
        self.blob = None
        self.version = 0
        self.uploads = 0
        self.fail = None
        monkeypatch.setattr(drive, "remote_meta", self.remote_meta)
        monkeypatch.setattr(drive, "download", self.download)
        monkeypatch.setattr(drive, "upload", self.upload)

    def remote_meta(self):
        if self.fail:
            raise self.fail
        return None if self.blob is None else {"id": "A", "version": str(self.version)}

    def download(self, dest):
        Path(dest).write_bytes(self.blob)

    def upload(self, src):
        if self.fail:
            raise self.fail
        self.blob = Path(src).read_bytes()
        self.version += 1
        self.uploads += 1
        return str(self.version)


@pytest.fixture
def world(tmp_path, monkeypatch):
    from door.core import workspace

    profile, jobs, backups = tmp_path / "profile", tmp_path / "jobs", tmp_path / "backups"
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs)
    monkeypatch.setattr(workspace, "BACKUPS_DIR", backups)
    fake = FakeDrive(monkeypatch, tmp_path)
    fake.profile, fake.jobs, fake.backups = profile, jobs, backups
    return fake


def _seed(world, text="{}"):
    world.profile.mkdir(exist_ok=True)
    (world.profile / "config.json").write_text(text)
    (world.profile / ".data_version").write_text("1")  # the data of this build, as `init` leaves it
    world.jobs.mkdir(exist_ok=True)
    (world.jobs / "history.json").write_text(text)


def test_push_uploads_and_records_the_baseline(world):
    _seed(world)
    result = sync.push()
    assert result["action"] == "push" and world.uploads == 1
    state = drive.read_state()
    assert state["synced_version"] == "1"
    assert state["fingerprint"] == sync.fingerprint(world.profile, world.jobs)
    assert state["last_synced"]


def test_push_skips_without_a_profile(world):
    assert sync.push()["action"] == "skipped"
    assert world.uploads == 0


def test_pull_on_a_fresh_clone_imports_and_records(world, tmp_path):
    _seed(world, '{"name": "A"}')
    sync.push()
    shutil.rmtree(world.profile)
    shutil.rmtree(world.jobs)
    result = sync.pull()
    assert result["action"] == "pull"
    assert json.loads((world.profile / "config.json").read_text()) == {"name": "A"}
    assert (world.jobs / "history.json").exists()
    state = drive.read_state()
    assert state["synced_version"] == "1"
    assert state["fingerprint"] == sync.fingerprint(world.profile, world.jobs)


def test_pull_keeps_only_the_newest_sync_backup(world):
    _seed(world, '{"v": 1}')
    sync.push()
    manual = world.backups / "manual-backup"
    manual.mkdir(parents=True)
    sync.pull()
    sync.pull()
    sync.pull()
    left = sorted(p.name for p in world.backups.iterdir() if p.name != "manual-backup")
    assert len(left) == 1
    assert manual.exists()


def test_sync_now_pushes_when_drive_is_empty(world):
    _seed(world)
    assert sync.sync_now()["action"] == "push"


def test_sync_now_does_nothing_when_in_step(world):
    _seed(world)
    sync.push()
    assert sync.sync_now()["action"] == "nothing"
    assert world.uploads == 1


def test_sync_now_pushes_local_changes(world):
    _seed(world)
    sync.push()
    (world.jobs / "new.json").write_text("x")
    assert sync.sync_now()["action"] == "push"
    assert world.uploads == 2


def test_sync_now_pulls_when_drive_moved_on(world):
    _seed(world, '{"v": 1}')
    sync.push()
    world.version += 1  # another computer pushed
    assert sync.sync_now()["action"] == "pull"


def test_sync_now_refuses_a_both_sides_change_and_overwrites_nothing(world):
    _seed(world, '{"v": 1}')
    sync.push()
    world.version += 1
    (world.jobs / "local.json").write_text("mine")
    with pytest.raises(sync.SyncConflict) as exc:
        sync.sync_now()
    assert "--keep-local" in str(exc.value) and "--keep-drive" in str(exc.value)
    assert (world.jobs / "local.json").read_text() == "mine"
    assert world.uploads == 1


def test_keep_local_pushes_and_keep_drive_pulls(world):
    _seed(world, '{"v": 1}')
    sync.push()
    world.version += 1
    (world.jobs / "local.json").write_text("mine")
    assert sync.sync_now(keep_local=True)["action"] == "push"
    world.version += 1
    (world.jobs / "later.json").write_text("unsynced")
    assert sync.sync_now(keep_drive=True)["action"] == "pull"
    assert not (world.jobs / "later.json").exists()


def test_first_sync_with_data_on_both_sides_conflicts(world):
    _seed(world)
    world.blob, world.version = b"x", 1
    drive.write_state({"refresh_token": "rt"})
    with pytest.raises(sync.SyncConflict):
        sync.sync_now()


def test_sync_now_when_not_connected(tmp_path, monkeypatch):
    monkeypatch.setattr(drive, "_BASE", tmp_path / "none")
    with pytest.raises(drive.DriveError, match="not connected"):
        sync.sync_now()


def test_a_failed_sync_now_records_its_error_and_the_next_one_clears_it(world):
    _seed(world)
    world.fail = drive.DriveError("Google Drive upload failed (HTTP 403)")
    with pytest.raises(drive.DriveError):
        sync.sync_now()
    assert drive.read_state()["last_error"] == "Google Drive upload failed (HTTP 403)"
    world.fail = None
    assert sync.sync_now()["action"] == "push"
    assert "last_error" not in drive.read_state()


def test_a_sync_now_conflict_is_not_recorded_as_a_failure(world):
    _seed(world)
    world.blob, world.version = b"x", 1
    with pytest.raises(sync.SyncConflict):
        sync.sync_now()
    assert "last_error" not in drive.read_state()


# --------------------------------------------------------------------------- lock hooks
def test_on_acquire_pulls_and_on_release_pushes_when_dirty(world):
    _seed(world, '{"v": 1}')
    sync.push()
    world.version += 1
    sync.on_acquire("run", world.jobs)
    assert drive.read_state()["synced_version"] == "2"
    (world.jobs / "x.json").write_text("new")
    sync.on_release("run", world.jobs)
    assert world.uploads == 2


def test_on_release_is_quiet_when_nothing_changed(world):
    _seed(world)
    sync.push()
    sync.on_acquire("run", world.jobs)
    sync.on_release("run", world.jobs)
    assert world.uploads == 1


def test_hooks_ignore_other_jobs_dirs_and_unconnected_computers(world, tmp_path):
    other = tmp_path / "elsewhere"
    sync.on_acquire("run", other)
    sync.on_release("run", other)
    drive.clear_state()
    sync.on_acquire("run", world.jobs)
    sync.on_release("run", world.jobs)
    assert world.uploads == 0


def test_offline_warns_once(world, progress_events):
    _seed(world)
    sync.push()
    world.fail = drive.DriveOffline("down")
    sync.on_acquire("run", world.jobs)
    (world.jobs / "x.json").write_text("new")
    sync.on_release("run", world.jobs)
    warnings = [e.message for e in progress_events if "Drive sync" in e.message]
    assert warnings == ["Drive sync skipped (offline)"]
    assert drive.read_state()["last_error"]


def test_the_hooks_note_each_pull_and_push_for_the_cli(world):
    _seed(world, '{"v": 1}')
    sync.push()
    sync.drain_notes()
    world.version += 1
    sync.on_acquire("run", world.jobs)
    (world.jobs / "x.json").write_text("new")
    sync.on_release("run", world.jobs)

    assert [kind for kind, _ in sync.drain_notes()] == ["pulled", "pushed"]
    assert sync.drain_notes() == []


def test_the_hooks_note_nothing_when_nothing_moved(world):
    _seed(world)
    sync.push()
    sync.drain_notes()
    sync.on_acquire("run", world.jobs)
    sync.on_release("run", world.jobs)

    assert sync.drain_notes() == []


def test_a_skipped_sync_is_noted_as_a_warning(world):
    _seed(world)
    sync.push()
    sync.drain_notes()
    world.fail = drive.DriveOffline("down")
    sync.on_acquire("run", world.jobs)

    assert sync.drain_notes() == [("warning", "Drive sync skipped (offline)")]


def test_fingerprint_ignores_the_usage_log(tmp_path):
    """The usage log (#575) is this computer's and is written outside the ledger lock: never a sync change."""
    from door.core import usage
    profile, jobs = _tree(tmp_path)
    base = sync.fingerprint(profile, jobs)
    (jobs / usage.LOG_NAME).write_text("{}\n")
    assert sync.fingerprint(profile, jobs) == base


# --------------------------------------------------------------------------- #
# data versions (#56)
# --------------------------------------------------------------------------- #
NEWER_SENTENCE = "Google Drive has data from a newer version of The other door; install it on this computer too"


def _blob(world, tmp_path, profile=None, jobs=None):
    """An archive of the sync format as another computer would have pushed it, with the given data versions."""
    import io
    import tarfile

    entries = {"manifest.json": json.dumps({"format": 1}).encode(), "profile/config.json": b"{}", "profile/cv.md": b"# drive"}
    if profile is not None:
        entries["profile/.data_version"] = str(profile).encode()
    if jobs is not None:
        entries["jobs/.data_version"] = str(jobs).encode()
    path = tmp_path / "blob.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    world.blob = path.read_bytes()
    world.version += 1


def _snapshot(world):
    return {
        p.relative_to(world.profile.parent).as_posix(): p.read_bytes()
        for root in (world.profile, world.jobs)
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name not in (".lock", ".lock.json")
    }


@pytest.fixture
def hooks(enable_sync_hooks):
    return enable_sync_hooks


def _connected_with_local(world):
    _seed(world, '{"v": 1}')
    sync.push()
    return world


def test_a_pull_of_an_older_archive_is_upgraded(world, tmp_path):
    from door.core import migrations

    _blob(world, tmp_path)
    sync.pull()
    assert (world.profile / ".data_version").read_text().strip() == str(migrations.current("profile"))
    assert drive.read_state()["refused_newer"] is False


def test_a_newer_archive_on_acquire_changes_nothing_and_says_so_once(world, tmp_path, hooks):
    _connected_with_local(world)
    before, state = _snapshot(world), drive.read_state()
    sync.drain_notes()
    _blob(world, tmp_path, profile=99)

    sync.on_acquire("run", world.jobs)

    assert _snapshot(world) == before
    assert not world.backups.exists()
    after = drive.read_state()
    assert after["synced_version"] == state["synced_version"] and after["fingerprint"] == state["fingerprint"]
    assert sync.drain_notes() == [("warning", NEWER_SENTENCE)]
    assert after["refused_newer"] is True and after["last_error"] == NEWER_SENTENCE
    assert after["data_versions"]["profile"] == 99

    (world.jobs / "x.json").write_text("changed")
    uploads = world.uploads
    sync.on_release("run", world.jobs)
    assert world.uploads == uploads


def test_while_refused_nothing_is_pushed(world, tmp_path, hooks):
    _connected_with_local(world)
    _blob(world, tmp_path, profile=99)
    sync.on_acquire("run", world.jobs)
    uploads = world.uploads

    with pytest.raises(drive.DriveError, match="newer version"):
        sync.push()
    with pytest.raises(drive.DriveError, match="newer version"):
        sync.sync_now(keep_local=True)
    assert world.uploads == uploads


def test_keep_drive_of_a_newer_archive_is_refused(world, tmp_path):
    from door.core import migrations

    _connected_with_local(world)
    before = _snapshot(world)
    _blob(world, tmp_path, profile=99)
    with pytest.raises(migrations.NewerData):
        sync.sync_now(keep_drive=True)
    assert _snapshot(world) == before


def test_local_data_below_the_recorded_versions_blocks_a_push(world):
    _connected_with_local(world)
    drive.update_state(data_versions={"profile": 99, "jobs": 0}, refused_newer=False)
    uploads = world.uploads
    with pytest.raises(drive.DriveError, match="newer version"):
        sync.push()
    assert world.uploads == uploads


def test_once_upgraded_a_pull_clears_the_refusal_and_a_push_works(world, tmp_path, monkeypatch, hooks):
    from door.core import migrations

    _connected_with_local(world)
    _blob(world, tmp_path, profile=2)
    sync.on_acquire("run", world.jobs)
    assert drive.read_state()["refused_newer"] is True
    sync.drain_notes()

    monkeypatch.setattr(migrations, "PROFILE_STEPS", [migrations.Step("a", lambda f: None), migrations.Step("b", lambda f: None)])
    sync.on_acquire("run", world.jobs)

    state = drive.read_state()
    assert state["refused_newer"] is False and "last_error" not in state
    assert (world.profile / ".data_version").read_text().strip() == "2"
    (world.jobs / "y.json").write_text("new")
    uploads = world.uploads
    sync.on_release("run", world.jobs)
    assert world.uploads == uploads + 1


def test_a_good_push_records_the_local_versions(world):
    from door.core import migrations

    _seed(world)
    migrations.write_version(world.profile, 1)
    sync.push()
    assert drive.read_state()["data_versions"] == {"profile": 1, "jobs": None}
    assert drive.read_state()["refused_newer"] is False
