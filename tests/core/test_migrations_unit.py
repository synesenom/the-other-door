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


def test_the_real_profile_step_is_idempotent_and_a_no_op_on_new_data(tmp_path):
    profile = tmp_path / "profile"
    _v010_profile(profile)
    step = migrations.PROFILE_STEPS[0]
    step.run(profile)
    snapshot = {p.name: p.read_bytes() for p in profile.rglob("*") if p.is_file()}
    step.run(profile)
    assert {p.name: p.read_bytes() for p in profile.rglob("*") if p.is_file()} == snapshot
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "config.json").write_text('{"name": "B"}')
    step.run(fresh)
    assert (fresh / "config.json").read_text() == '{"name": "B"}'


def test_the_real_profile_step_on_a_missing_folder(tmp_path):
    migrations.PROFILE_STEPS[0].run(tmp_path / "nothing")
    assert not (tmp_path / "nothing").exists()


def test_current_version_is_the_number_of_steps():
    assert migrations.current("profile") == len(migrations.PROFILE_STEPS) == 1
    assert migrations.current("jobs") == len(migrations.JOBS_STEPS)


# ---- the runner ----------------------------------------------------------------------------------------


def test_runs_only_the_missing_steps_in_order(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    order = []
    steps = [Step("a", lambda f: order.append("a")), Step("b", lambda f: order.append("b")), Step("c", lambda f: order.append("c"))]
    (profile / ".data_version").write_text("1\n")
    status = migrations.upgrade_all(profile, jobs, backups, profile_steps=steps, jobs_steps=[])
    assert order == ["b", "c"]
    assert status is None
    assert (profile / ".data_version").read_text() == "3\n"


def test_no_file_on_a_folder_with_data_is_version_zero(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    migrations.upgrade_all(profile, jobs, backups, profile_steps=[_tag("a")], jobs_steps=[_tag("j")])
    assert (profile / "a.done").exists() and (jobs / "j.done").exists()
    assert (profile / ".data_version").read_text() == "1\n"
    assert (jobs / ".data_version").read_text() == "1\n"


def test_a_current_folder_is_left_alone_with_no_backup(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    (profile / ".data_version").write_text("1\n")
    (jobs / ".data_version").write_text("0\n")
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
        (b,) = backups.glob("upgrade-profile-0-1-*")
        seen["config"] = (b / "config.json").read_text()
        seen["has_marker"] = (b / "a.done").exists()
    migrations.upgrade_all(profile, jobs, backups, profile_steps=[Step("a", step)], jobs_steps=[])
    assert seen == {"config": "{}", "has_marker": False}


def test_the_jobs_backup_leaves_the_lock_files_out(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    migrations.upgrade_all(profile, jobs, backups, profile_steps=[], jobs_steps=[_tag("j")])
    (b,) = backups.glob("upgrade-jobs-0-1-*")
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
    (profile / ".data_version").write_text("0\n")

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
    assert (profile / ".data_version").read_text() == "0\n"
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
    (profile / ".data_version").write_text("5\n")
    status = migrations.upgrade_all(profile, jobs, backups, profile_steps=[_tag("a")], jobs_steps=[_tag("j")])
    assert status == {
        "state": "newer",
        "message": "This data was written by a newer version of The other door. Install the latest version.",
    }
    assert not (jobs / "j.done").exists() and not (jobs / ".data_version").exists()
    assert (profile / ".data_version").read_text() == "5\n"
    assert not backups.exists()


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
    (tmp_path / ".data_version").write_text("2\n")
    assert migrations.read_version(tmp_path) == 2
    for bad in ("", "x", "-1", "1.5"):
        (tmp_path / ".data_version").write_text(bad)
        with pytest.raises(migrations.DataVersionError):
            migrations.read_version(tmp_path)


def test_a_state_clears_when_the_data_is_current_again(home):
    profile, jobs, backups = home
    _make(profile, jobs)
    (profile / ".data_version").write_text("5\n")
    assert migrations.upgrade_all(profile, jobs, backups, profile_steps=[_tag("a")], jobs_steps=[])["state"] == "newer"
    (profile / ".data_version").write_text("1\n")
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
    assert (profile / ".data_version").read_text() == "1\n"


def test_stamp_new_writes_the_current_version_only_for_a_new_folder(tmp_path):
    profile = tmp_path / "profile"
    migrations.stamp_new(profile)
    assert (profile / ".data_version").read_text() == f"{migrations.current('profile')}\n"
    (profile / ".data_version").write_text("0\n")
    migrations.stamp_new(profile)
    assert (profile / ".data_version").read_text() == "0\n"


def test_the_app_test_world_stamps_the_current_profile_version():
    """The journeys' world is a profile set up by this build: stamped like `init` stamps one, or every journey
    would run the upgrade at start (and find an extra backup)."""
    import re
    from paths import REPO_ROOT

    build = (REPO_ROOT / "app" / "test" / "world" / "build.ts").read_text(encoding="utf-8")
    assert int(re.search(r"PROFILE_DATA_VERSION = (\d+)", build).group(1)) == migrations.current("profile")
