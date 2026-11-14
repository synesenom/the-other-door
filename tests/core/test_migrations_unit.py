"""The upgrade of a user's data between releases (#56): versions, steps, backup, failure, newer data."""

import json
import multiprocessing
import os
import shutil
import threading
from pathlib import Path

import pytest

from door.core import lock as lock_mod
from door.core import migrations, workspace
from door.core.migrations import Step

EXAMPLE = workspace.PROFILE_EXAMPLE_DIR


_REAL_RUN_AT_START = migrations.run_at_start  # conftest stubs it per test; these tests run the real one


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    monkeypatch.setattr(migrations, "_state", None)
    monkeypatch.setattr(migrations, "_LOCK_WAIT_S", 0.0)


@pytest.fixture
def home(tmp_path):
    return tmp_path / "profile", tmp_path / "jobs", tmp_path / "backups"


def _tag(name):
    """A step that leaves a file named *name* in its folder."""
    def run(folder: Path) -> None:
        (folder / f"{name}.done").write_text("x")
    return Step(name, run)


def _make(profile, jobs):
    profile.mkdir(parents=True, exist_ok=True)
    jobs.mkdir(parents=True, exist_ok=True)
    (profile / "config.json").write_text("{}")
    (jobs / "history.json").write_text("{}")


# ---- the real steps ------------------------------------------------------------------------------------


def _v010_profile(profile: Path) -> None:
    """What `init` of v0.1.0 left: the templates and fonts copied, the config naming them."""
    profile.mkdir(parents=True, exist_ok=True)
    for name in ("cv.template.tex", "cover-letter.template.tex"):
        shutil.copy2(EXAMPLE / name, profile / name)
    shutil.copytree(EXAMPLE / "fonts", profile / "fonts")
    config = {
        "name": "Ada",
        "role_targets": ["x"],
        "cv_template": "profile/cv.template.tex",
        "cover_letter_template": "profile/cover-letter.template.tex",
    }
    (profile / "config.json").write_text(json.dumps(config, indent=2))
    (profile / "cv.md").write_text("# Ada\n")


def test_the_real_profile_step_removes_unedited_copies_and_default_keys(tmp_path):
    profile = tmp_path / "profile"
    _v010_profile(profile)
    migrations.PROFILE_STEPS[0].run(profile)
    assert not (profile / "cv.template.tex").exists()
    assert not (profile / "cover-letter.template.tex").exists()
    assert not (profile / "fonts").exists()
    assert json.loads((profile / "config.json").read_text()) == {"name": "Ada", "role_targets": ["x"]}
    assert (profile / "cv.md").read_text() == "# Ada\n"


def test_the_real_profile_step_keeps_an_edited_template_and_its_key(tmp_path):
    profile = tmp_path / "profile"
    _v010_profile(profile)
    (profile / "cv.template.tex").write_text("my own styling")
    (profile / "fonts" / "Figtree-Regular.otf").write_bytes(b"mine")
    migrations.PROFILE_STEPS[0].run(profile)
    assert (profile / "cv.template.tex").read_text() == "my own styling"
    assert (profile / "fonts" / "Figtree-Regular.otf").read_bytes() == b"mine"
    assert not (profile / "cover-letter.template.tex").exists()
    assert not (profile / "fonts" / "YoungSerif-Bold.otf").exists()
    config = json.loads((profile / "config.json").read_text())
    assert config["cv_template"] == "profile/cv.template.tex"
    assert "cover_letter_template" not in config


def test_the_real_profile_step_leaves_a_template_the_user_pointed_elsewhere(tmp_path):
    profile = tmp_path / "profile"
    _v010_profile(profile)
    config = json.loads((profile / "config.json").read_text())
    config["cv_template"] = "/home/ada/mine.tex"
    (profile / "config.json").write_text(json.dumps(config))
    migrations.PROFILE_STEPS[0].run(profile)
    assert json.loads((profile / "config.json").read_text())["cv_template"] == "/home/ada/mine.tex"


def test_the_real_profile_step_on_a_missing_folder(tmp_path):
    migrations.PROFILE_STEPS[0].run(tmp_path / "nothing")
    assert not (tmp_path / "nothing").exists()


def test_current_version_is_the_app_major_and_the_number_of_steps():
    assert migrations.current("profile") == migrations.Version(0, 1)
    assert len(migrations.PROFILE_STEPS) == 1
    assert migrations.current("jobs") == migrations.Version(0, len(migrations.JOBS_STEPS))


def test_the_major_is_read_from_the_app_version_at_call_time(monkeypatch):
    from door import version

    monkeypatch.setattr(version, "VERSION", "3.2.1")
    assert migrations.current("profile") == migrations.Version(3, 1)


# ---- the runner ----------------------------------------------------------------------------------------


def test_runs_only_the_missing_steps_in_order(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    order = []
    steps = [Step("a", lambda f: order.append("a")), Step("b", lambda f: order.append("b")), Step("c", lambda f: order.append("c"))]
    (profile / ".data_version").write_text("0.1\n")
    status = migrations.upgrade_all(profile, jobs, backups, profile_steps=steps, jobs_steps=[])
    assert order == ["b", "c"]
    assert status is None
    assert (profile / ".data_version").read_text() == "0.3\n"


def test_no_file_on_a_folder_with_data_is_version_zero(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    migrations.upgrade_all(profile, jobs, backups, profile_steps=[_tag("a")], jobs_steps=[_tag("j")])
    assert (profile / "a.done").exists() and (jobs / "j.done").exists()
    assert (profile / ".data_version").read_text() == "0.1\n"
    assert (jobs / ".data_version").read_text() == "0.1\n"


def test_a_current_folder_is_left_alone_with_no_backup(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    (profile / ".data_version").write_text("0.1\n")
    (jobs / ".data_version").write_text("0.0\n")
    migrations.upgrade_all(profile, jobs, backups, profile_steps=[_tag("a")], jobs_steps=[])
    assert not (profile / "a.done").exists()
    assert not backups.exists()


def test_a_missing_folder_is_not_created(home):
    profile, jobs, backups = home
    migrations.upgrade_all(profile, jobs, backups, profile_steps=[_tag("a")], jobs_steps=[_tag("j")])
    assert not profile.exists() and not jobs.exists() and not backups.exists()
    assert migrations.status() is None


def test_backup_is_taken_before_the_steps_and_holds_the_old_data(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    seen = {}

    def step(folder):
        (b,) = backups.glob("upgrade-profile-0.0-0.1-*")
        seen["config"] = (b / "config.json").read_text()
        seen["has_marker"] = (b / "a.done").exists()
    migrations.upgrade_all(profile, jobs, backups, profile_steps=[Step("a", step)], jobs_steps=[])
    assert seen == {"config": "{}", "has_marker": False}


def test_the_jobs_backup_leaves_the_lock_files_out(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    migrations.upgrade_all(profile, jobs, backups, profile_steps=[], jobs_steps=[_tag("j")])
    (b,) = backups.glob("upgrade-jobs-0.0-0.1-*")
    assert (b / "history.json").exists()
    assert not (b / ".lock").exists() and not (b / ".lock.json").exists()


def test_only_the_two_newest_upgrade_backups_are_kept_and_import_backups_stay(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    (backups / "2026-01-01T10-00").mkdir(parents=True)
    for n in range(4):
        old = backups / f"upgrade-profile-{n}-{n + 1}-20260101-00000{n}"
        old.mkdir()
        os.utime(old, (1_700_000_000 + n, 1_700_000_000 + n))
    migrations.upgrade_all(profile, jobs, backups, profile_steps=[_tag("a")], jobs_steps=[])
    kept = sorted(p.name for p in backups.glob("upgrade-*"))
    assert len(kept) == 2
    assert "upgrade-profile-3-4-20260101-000003" in kept  # the newest old one stays beside the new one
    assert not any(name.startswith("upgrade-profile-0-1-20260101") for name in kept)
    assert (backups / "2026-01-01T10-00").is_dir()


def test_a_failing_step_restores_the_folder_and_keeps_the_version(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    (profile / ".data_version").write_text("0.0\n")

    def bad(folder):
        (folder / "config.json").write_text("broken")
        (folder / "new.txt").write_text("x")
        (folder / "sub").mkdir()
        raise RuntimeError("boom")
    status = migrations.upgrade_all(profile, jobs, backups, profile_steps=[_tag("a"), Step("rename sectors", bad)], jobs_steps=[])
    assert status["state"] == "failed"
    assert status["message"] == (
        "Your data could not be upgraded to this version: rename sectors. Nothing was changed. Send a report from Settings."
    )
    assert (profile / "config.json").read_text() == "{}"
    assert not (profile / "new.txt").exists() and not (profile / "sub").exists() and not (profile / "a.done").exists()
    assert (profile / ".data_version").read_text() == "0.0\n"
    assert migrations.status() == status


def test_a_failure_leaves_one_line_in_the_problem_log(home, monkeypatch):
    profile, jobs, backups = home
    _make(profile, jobs)
    lines = []
    monkeypatch.setattr(migrations.problem_log, "failure", lambda where, message: lines.append((where, message)))

    def bad(folder):
        raise RuntimeError("boom")
    migrations.upgrade_all(profile, jobs, backups, profile_steps=[Step("s", bad)], jobs_steps=[])
    assert len(lines) == 1 and "s" in lines[0][1] and "boom" in lines[0][1]


def test_a_failed_profile_stops_before_the_jobs(home):
    profile, jobs, backups = home
    _make(profile, jobs)

    def bad(folder):
        raise RuntimeError("boom")
    migrations.upgrade_all(profile, jobs, backups, profile_steps=[Step("s", bad)], jobs_steps=[_tag("j")])
    assert not (jobs / "j.done").exists()


def test_newer_data_is_refused_and_nothing_is_written(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    (profile / ".data_version").write_text("0.5\n")
    status = migrations.upgrade_all(profile, jobs, backups, profile_steps=[_tag("a")], jobs_steps=[_tag("j")])
    assert status == {
        "state": "newer",
        "message": "This data was written by a newer version of The other door. Install the latest version.",
    }
    assert not (jobs / "j.done").exists() and not (jobs / ".data_version").exists()
    assert (profile / ".data_version").read_text() == "0.5\n"
    assert not backups.exists()


def test_data_of_an_older_major_is_refused_and_nothing_is_written(home, monkeypatch):
    from door import version

    monkeypatch.setattr(version, "VERSION", "1.0.0")
    profile, jobs, backups = home
    _make(profile, jobs)
    (profile / ".data_version").write_text("0.1\n")
    status = migrations.upgrade_all(profile, jobs, backups, profile_steps=[], jobs_steps=[_tag("j")])
    assert status == {
        "state": "old_major",
        "message": "This data was written by The other door 0.x. Version 1 cannot open it: keep using 0.x, "
        "or start a new profile.",
    }
    assert not (jobs / "j.done").exists() and not backups.exists()
    assert (profile / ".data_version").read_text() == "0.1\n"


def test_a_folder_with_data_and_no_file_is_0_0_so_too_old_for_a_later_major(home, monkeypatch):
    from door import version

    monkeypatch.setattr(version, "VERSION", "1.0.0")
    profile, jobs, backups = home
    _make(profile, jobs)
    assert migrations.upgrade_all(profile, jobs, backups, profile_steps=[], jobs_steps=[])["state"] == "old_major"


def test_data_of_a_later_major_is_newer(home, monkeypatch):
    profile, jobs, backups = home
    _make(profile, jobs)
    (jobs / ".data_version").write_text("1.0\n")
    assert migrations.upgrade_all(profile, jobs, backups, profile_steps=[], jobs_steps=[])["state"] == "newer"


def test_a_garbled_version_file_is_a_failure_not_zero(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    (profile / ".data_version").write_text("banana")
    status = migrations.upgrade_all(profile, jobs, backups, profile_steps=[_tag("a")], jobs_steps=[])
    assert status["state"] == "failed"
    assert not (profile / "a.done").exists()
    assert (profile / ".data_version").read_text() == "banana"


def test_read_version(tmp_path):
    assert migrations.read_version(tmp_path) is None
    (tmp_path / ".data_version").write_text("2.5\n")
    assert migrations.read_version(tmp_path) == migrations.Version(2, 5)
    for bad in ("", "x", "-1", "1", "1.5.2", "1.-2", "a.b", "1.", ".1", "1. 5", "0.1x"):
        (tmp_path / ".data_version").write_text(bad)
        with pytest.raises(migrations.DataVersionError):
            migrations.read_version(tmp_path)


def test_a_state_clears_when_the_data_is_current_again(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    (profile / ".data_version").write_text("0.5\n")
    assert migrations.upgrade_all(profile, jobs, backups, profile_steps=[_tag("a")], jobs_steps=[])["state"] == "newer"
    (profile / ".data_version").write_text("0.1\n")
    assert migrations.upgrade_all(profile, jobs, backups, profile_steps=[_tag("a")], jobs_steps=[]) is None
    assert migrations.status() is None


def test_a_busy_lock_is_busy_then_retried_lazily(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    steps = dict(profile_steps=[_tag("a")], jobs_steps=[])
    release = threading.Event()
    held = threading.Event()

    def holder():
        # another process, as far as the lock can tell: a different thread of this one
        with lock_mod.ledger_lock(jobs, "run"):
            held.set()
            release.wait(5)
    t = threading.Thread(target=holder)
    t.start()
    held.wait(5)
    try:
        status = migrations.upgrade_all(profile, jobs, backups, **steps)
        assert status["state"] == "busy"
        assert "run is in progress" in status["message"]
        assert not (profile / "a.done").exists()
    finally:
        release.set()
        t.join()
    assert migrations.upgrade_all(profile, jobs, backups, **steps) is None
    assert (profile / "a.done").exists()
    assert migrations.status() is None


def _upgrade_in_process(profile, jobs, backups, counter):
    migrations._LOCK_WAIT_S = 10.0  # the second one waits for the first, then finds it done
    def step(folder):
        with open(counter, "a") as fh:
            fh.write("x")
    migrations.upgrade_all(Path(profile), Path(jobs), Path(backups), profile_steps=[Step("a", step)], jobs_steps=[])


def test_two_processes_at_once_the_second_finds_it_done(home, tmp_path):
    profile, jobs, backups = home
    _make(profile, jobs)
    counter = tmp_path / "counter"
    ctx = multiprocessing.get_context("fork")
    procs = [ctx.Process(target=_upgrade_in_process, args=(str(profile), str(jobs), str(backups), str(counter))) for _ in range(2)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    assert counter.read_text() == "x"
    assert (profile / ".data_version").read_text() == "0.1\n"


def test_ensure_folder_stamps_a_folder_it_creates_or_finds_empty(tmp_path):
    profile = tmp_path / "profile"
    migrations.ensure_folder(profile, "profile")
    assert (profile / ".data_version").read_text() == "0.1\n"
    empty = tmp_path / "jobs"
    empty.mkdir()
    (empty / ".lock").write_text("")
    migrations.ensure_folder(empty, "jobs")
    assert (empty / ".data_version").read_text() == "0.0\n"


def test_ensure_folder_leaves_a_folder_with_data_or_a_version_alone(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "config.json").write_text("{}")
    migrations.ensure_folder(old, "profile")
    assert not (old / ".data_version").exists()  # v0.1.0's data: the upgrade at start dates it
    (old / ".data_version").write_text("0.0\n")
    migrations.ensure_folder(old, "profile")
    assert (old / ".data_version").read_text() == "0.0\n"


def test_the_app_stamps_the_data_versions_this_build_writes():
    """The journeys' world and the app's demo are folders set up by this build: stamped like `init` stamps them, or
    every start would run the upgrade (and find an extra backup). The app has one place for the two versions
    (`app/src/main/data-versions.ts`) that this test keeps equal to `migrations.current`; a release that adds a step
    changes that file (dev-release, the data-migrator)."""
    import re
    from paths import REPO_ROOT

    app = REPO_ROOT / "app"
    versions = (app / "src" / "main" / "data-versions.ts").read_text(encoding="utf-8")
    assert re.search(r"PROFILE_DATA_VERSION = '([\d.]+)'", versions).group(1) == str(migrations.current("profile"))
    assert re.search(r"JOBS_DATA_VERSION = '([\d.]+)'", versions).group(1) == str(migrations.current("jobs"))
    for path in (app / "test" / "world" / "build.ts", app / "src" / "main" / "demo.ts"):
        text = path.read_text(encoding="utf-8")
        assert "data-versions" in text and not re.search(r"DATA_VERSION = '", text), path.name


# --------------------------------------------------------------------------- #
# refuse (import and Drive)
# --------------------------------------------------------------------------- #
V = migrations.Version


def test_refuse_passes_current_older_and_missing_versions():
    migrations.refuse({"profile": migrations.current("profile"), "jobs": migrations.current("jobs")})
    migrations.refuse({"profile": V(0, 0), "jobs": None})
    migrations.refuse({"profile": None, "jobs": None})


@pytest.mark.parametrize("folder", ["profile", "jobs"])
def test_refuse_raises_newer_for_either_folder(folder):
    versions = {"profile": None, "jobs": None, folder: V(0, migrations.current(folder).n + 1)}
    with pytest.raises(migrations.RefusedData) as caught:
        migrations.refuse(versions)
    assert caught.value.state == "newer"
    assert str(caught.value) == migrations.ARCHIVE_NEWER
    assert caught.value.versions == versions


def test_refuse_raises_old_major_and_names_the_majors(monkeypatch):
    from door import version

    monkeypatch.setattr(version, "VERSION", "2.0.0")
    with pytest.raises(migrations.RefusedData) as caught:
        migrations.refuse({"profile": V(1, 4), "jobs": None})
    assert caught.value.state == "old_major"
    assert str(caught.value) == migrations.OLD_MAJOR.format(data=1, app=2)


def test_the_version_orders_by_major_then_steps():
    assert V(0, 5) < V(1, 0) < V(1, 1)
    assert str(V(1, 2)) == "1.2"
    assert V.parse("1.2") == V(1, 2)


def test_start_creates_both_folders_stamped_so_no_later_writer_leaves_one_unversioned(tmp_path, monkeypatch):
    from door.core import workspace

    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "profile")
    monkeypatch.setattr(workspace, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(workspace, "BACKUPS_DIR", tmp_path / "backups")

    assert _REAL_RUN_AT_START() is None

    for name in ("profile", "jobs"):
        assert migrations.read_version(tmp_path / name) == migrations.current(name)
    (tmp_path / "profile" / "cv.md").write_text("# CV")  # a writer that never calls ensure_folder
    assert migrations.read_version(tmp_path / "profile") == migrations.current("profile")


def test_start_leaves_an_unversioned_folder_with_data_to_the_upgrade(tmp_path, monkeypatch):
    from door.core import workspace

    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "profile")
    monkeypatch.setattr(workspace, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(workspace, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(migrations, "PROFILE_STEPS", [_tag("a")])
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "config.json").write_text("{}")

    assert _REAL_RUN_AT_START() is None

    assert (tmp_path / "profile" / "a.done").exists()  # read as 0.0 and upgraded, not stamped over


# ---- review gaps of #56 ----------------------------------------------------------------------------------


def test_a_kill_after_a_step_is_restored_and_upgraded_at_the_next_start(home):
    """A step that ran and a process that died before the version was written: the next start restores the backup
    (not new-shape data under the old version) and runs the steps again."""
    profile, jobs, backups = home
    _make(profile, jobs)
    (profile / "cv.md").write_text("old shape")
    seen = []

    def rewrite(folder):
        seen.append((folder / "cv.md").read_text())
        (folder / "cv.md").write_text("new shape")

    # what a hard kill after a step leaves: the backup, the marker, new-shape data, the old version
    backup = migrations._backup(profile, backups, "profile", migrations.UNVERSIONED, migrations.Version(0, 1))
    (profile / migrations.MARKER).write_text(str(backup))
    (profile / "cv.md").write_text("new shape")
    (profile / "extra.json").write_text("{}")
    migrations._set(None)
    assert migrations.upgrade_all(profile, jobs, backups, profile_steps=[Step("rewrite", rewrite)], jobs_steps=[]) is None
    assert seen == ["old shape"]
    assert not (profile / "extra.json").exists()
    assert (profile / ".data_version").read_text() == "0.1\n"
    assert not (profile / migrations.MARKER).exists()


def test_the_marker_is_there_while_a_step_runs_and_gone_after(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    during = []
    migrations.upgrade_all(
        profile, jobs, backups,
        profile_steps=[Step("s", lambda folder: during.append((folder / migrations.MARKER).exists()))], jobs_steps=[],
    )
    assert during == [True]
    assert not (profile / migrations.MARKER).exists()


def test_a_marker_beside_the_current_version_is_only_removed(home):
    """Killed between writing the version and removing the marker: the data is upgraded, do not restore."""
    profile, jobs, backups = home
    _make(profile, jobs)
    (profile / "cv.md").write_text("upgraded")
    (profile / ".data_version").write_text("0.1\n")
    old = backups / "upgrade-profile-0.0-0.1-20260101-000000"
    old.mkdir(parents=True)
    (old / "cv.md").write_text("stale")
    (profile / migrations.MARKER).write_text(str(old))
    migrations.upgrade_folder(profile, [_tag("a")], backups_dir=backups, label="profile")
    assert (profile / "cv.md").read_text() == "upgraded"
    assert not (profile / migrations.MARKER).exists()


def test_a_failure_removes_the_marker_and_repeated_failures_keep_two_backups(home, monkeypatch):
    profile, jobs, backups = home
    _make(profile, jobs)

    def bad(folder):
        raise RuntimeError("boom")
    stamps = iter(range(10))
    real_backup = migrations._backup

    def numbered(folder, backups_dir, label, source, target):
        dest = real_backup(folder, backups_dir, label, source, target)
        n = next(stamps)
        os.utime(dest, (1_700_000_000 + n, 1_700_000_000 + n))
        return dest
    monkeypatch.setattr(migrations, "_backup", numbered)
    for _ in range(5):
        migrations._set(None)
        assert migrations.upgrade_all(profile, jobs, backups, profile_steps=[Step("s", bad)], jobs_steps=[])["state"] == "failed"
    assert len(list(backups.glob("upgrade-*"))) == migrations.KEEP_BACKUPS
    assert not (profile / migrations.MARKER).exists()


def test_a_jobs_folder_with_only_the_usage_log_is_still_unstamped_empty(tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "usage.jsonl").write_text("{}\n")
    migrations.ensure_folder(jobs, "jobs")
    assert (jobs / ".data_version").read_text() == "0.0\n"


def test_two_stamps_at_once_do_not_fail(tmp_path):
    folder = tmp_path / "jobs"
    folder.mkdir()
    errors = []
    barrier = threading.Barrier(8)

    def stamp():
        barrier.wait()
        try:
            for _ in range(50):
                migrations.write_version(folder, migrations.Version(0, 1))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    threads = [threading.Thread(target=stamp) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    assert (folder / ".data_version").read_text() == "0.1\n"
    assert [p.name for p in folder.iterdir()] == [".data_version"]


def test_ensure_folder_tolerates_the_stamp_appearing_meanwhile(tmp_path, monkeypatch):
    folder = tmp_path / "profile"
    folder.mkdir()
    real = migrations.write_version

    def racing(path, version, **kwargs):
        (Path(path) / ".data_version").write_text("0.1\n")  # the other process got there first
        return real(path, version, **kwargs)
    monkeypatch.setattr(migrations, "write_version", racing)
    migrations.ensure_folder(folder, "profile")
    assert (folder / ".data_version").read_text() == "0.1\n"
