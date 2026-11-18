"""`export` / `import` cores: the archive's contents, the swap-in, the backups and the refusals."""

import io
import json
import tarfile
import types
from pathlib import Path

import pytest

from door.core import archive as archive_core
from door.core import migrations, workspace
from profile_utils import write_config


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A populated workspace, plus an empty one to import into."""
    src = tmp_path / "src"
    profile_dir = src / "profile"
    jobs_dir = src / "jobs"
    profile_dir.mkdir(parents=True)
    write_config(profile_dir, {"role_targets": ["x"], "location": "Copenhagen"})
    (profile_dir / "cv.md").write_text("# My CV")
    posting = jobs_dir / "postings" / "2026-10-09" / "jobindex" / "jobindex-acme-ds.json"
    posting.parent.mkdir(parents=True)
    posting.write_text('{"id": "jobindex-acme-ds", "score": 0.8}')
    (jobs_dir / "applications.json").write_text('{"jobindex-acme-ds": {"status": "applied"}}')
    (jobs_dir / "output" / "jobindex-acme-ds").mkdir(parents=True)
    (jobs_dir / "output" / "jobindex-acme-ds" / "cv.pdf").write_bytes(b"%PDF-1.5")
    (jobs_dir / ".lock").write_text("")
    (jobs_dir / ".lock.json").write_text('{"pid": 1}')

    dst = tmp_path / "dst"
    dst.mkdir()
    backups_dir = dst / "backups"

    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(workspace, "BACKUPS_DIR", backups_dir)
    monkeypatch.chdir(tmp_path)
    return types.SimpleNamespace(
        tmp_path=tmp_path, profile_dir=profile_dir, jobs_dir=jobs_dir,
        dst_profile=dst / "profile", dst_jobs=dst / "jobs", backups_dir=backups_dir,
    )


def _export(env, path=None):
    return archive_core._export_core(path, profile_dir=env.profile_dir, jobs_dir=env.jobs_dir)


def _import(env, archive):
    return archive_core._import_core(
        archive, profile_dir=env.dst_profile, jobs_dir=env.dst_jobs, backups_dir=env.backups_dir
    )


def _names(archive):
    with tarfile.open(archive) as tar:
        return {m.name for m in tar.getmembers() if m.isfile()}


def _tar_with(tmp_path, entries, *, manifest=True, name="custom.tar.gz"):
    """A hand-made archive: `entries` maps member name -> bytes (or a TarInfo for odd types)."""
    path = tmp_path / name
    with tarfile.open(path, "w:gz") as tar:
        if manifest:
            entries = {"manifest.json": json.dumps({"format": 1}).encode(), **entries}
        for member, data in entries.items():
            if isinstance(data, tarfile.TarInfo):
                tar.addfile(data)
                continue
            info = tarfile.TarInfo(member)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path




# --------------------------------------------------------------------------- #
# _export_core
# --------------------------------------------------------------------------- #

def test_export_writes_profile_and_jobs_without_the_lock(env):
    result = _export(env, env.tmp_path / "out.tar.gz")

    names = _names(result["path"])
    assert "manifest.json" in names
    assert "profile/config.json" in names
    assert "profile/cv.md" in names
    assert "jobs/postings/2026-10-09/jobindex/jobindex-acme-ds.json" in names
    assert "jobs/applications.json" in names
    assert "jobs/output/jobindex-acme-ds/cv.pdf" in names
    assert "jobs/.lock" not in names
    assert "jobs/.lock.json" not in names
    assert result["files"] == len(names) - 1  # the manifest isn't counted
    assert result["bytes"] > 0


def test_the_employer_list_travels_with_the_profile(env):
    from door.core import companies

    companies.save(env.profile_dir, [companies.Company(
        name="BEC", feed=companies.Feed(platform="hr_manager", id="bec"), status="followed", found_via="manual")])

    archive = _export(env, env.tmp_path / "out.tar.gz")["path"]
    _import(env, archive)

    assert "profile/companies.json" in _names(archive)
    assert companies.feed_entries(env.dst_profile, "hr_manager") == ["bec"]


def test_export_manifest_names_the_format(env):
    result = _export(env, env.tmp_path / "out.tar.gz")
    with tarfile.open(result["path"]) as tar:
        manifest = json.load(tar.extractfile("manifest.json"))
    assert manifest["format"] == 1
    assert "exported_at" in manifest


def test_export_default_path_is_dated_in_the_current_directory(env):
    result = _export(env)
    path = Path(result["path"])
    assert path.parent == env.tmp_path
    assert path.name.startswith("door-export-") and path.name.endswith(".tar.gz")


def test_export_into_a_directory_uses_the_default_name(env):
    out = env.tmp_path / "usb"
    out.mkdir()
    result = _export(env, out)
    assert Path(result["path"]).parent == out
    assert Path(result["path"]).name.startswith("door-export-")


def test_export_refuses_to_overwrite(env):
    target = env.tmp_path / "out.tar.gz"
    target.write_text("keep me")
    with pytest.raises(FileExistsError, match="already exists"):
        _export(env, target)
    assert target.read_text() == "keep me"


def test_export_refuses_a_path_inside_the_data(env):
    with pytest.raises(ValueError, match="outside"):
        _export(env, env.jobs_dir / "out.tar.gz")


def test_export_without_a_profile_is_an_error(env, tmp_path):
    with pytest.raises(FileNotFoundError, match="nothing to export"):
        archive_core._export_core(tmp_path / "x.tar.gz", profile_dir=tmp_path / "none", jobs_dir=env.jobs_dir)


def test_export_works_without_jobs(env, tmp_path):
    result = archive_core._export_core(tmp_path / "x.tar.gz", profile_dir=env.profile_dir, jobs_dir=tmp_path / "nojobs")
    assert {n for n in _names(result["path"]) if n.startswith("jobs/")} <= {"jobs/", "jobs/.data_version"}  # the lock stamps it


def test_export_holds_the_ledger_lock(env, monkeypatch):
    from door.core.lock import lock_holder

    seen = {}
    real = archive_core._add_tree

    def spy(tar, root, arcname, exclude):
        seen["holder"] = lock_holder(env.jobs_dir)
        return real(tar, root, arcname, exclude)

    monkeypatch.setattr(archive_core, "_add_tree", spy)
    _export(env, env.tmp_path / "out.tar.gz")
    assert seen["holder"]["purpose"] == "export"


# --------------------------------------------------------------------------- #
# _import_core
# --------------------------------------------------------------------------- #

def test_round_trip_into_an_empty_workspace(env):
    archive = _export(env, env.tmp_path / "out.tar.gz")["path"]

    result = _import(env, archive)

    assert (env.dst_profile / "cv.md").read_text() == "# My CV"
    assert json.loads((env.dst_profile / "config.json").read_text())["location"] == "Copenhagen"
    assert (env.dst_jobs / "postings" / "2026-10-09" / "jobindex" / "jobindex-acme-ds.json").exists()
    assert (env.dst_jobs / "output" / "jobindex-acme-ds" / "cv.pdf").read_bytes() == b"%PDF-1.5"
    assert result["backup_dir"] is None  # nothing was there to back up
    assert result["files"] == _export(env, env.tmp_path / "again.tar.gz")["files"]


def test_import_sweeps_a_stale_staging_folder_a_killed_import_left(env):
    import os, time
    from door.core import utils
    archive = _export(env, env.tmp_path / "out.tar.gz")["path"]
    stale = env.dst_profile.parent / ".door-import-x.part"
    stale.mkdir()
    old = time.time() - 2 * utils.STALE_PART_SECONDS
    os.utime(stale, (old, old))
    _import(env, archive)
    assert not stale.exists()


def test_import_into_folders_that_hold_only_their_version_makes_no_backup(env):
    archive = _export(env, env.tmp_path / "out.tar.gz")["path"]
    migrations.ensure_folder(env.dst_profile, "profile")  # what a first start leaves
    migrations.ensure_folder(env.dst_jobs, "jobs")

    result = _import(env, archive)

    assert result["backup_dir"] is None
    assert (env.dst_profile / "cv.md").read_text() == "# My CV"


def test_import_replaces_existing_data_and_backs_it_up(env):
    archive = _export(env, env.tmp_path / "out.tar.gz")["path"]
    env.dst_profile.mkdir()
    (env.dst_profile / "cv.md").write_text("# Old CV")
    (env.dst_jobs / "postings" / "2026-01-01" / "thehub").mkdir(parents=True)
    (env.dst_jobs / "postings" / "2026-01-01" / "thehub" / "old.json").write_text("{}")

    result = _import(env, archive)

    assert (env.dst_profile / "cv.md").read_text() == "# My CV"
    assert not (env.dst_jobs / "postings" / "2026-01-01").exists()  # replaced, not merged
    backup = Path(result["backup_dir"])
    assert backup.parent == env.backups_dir
    assert (backup / "profile" / "cv.md").read_text() == "# Old CV"
    assert (backup / "jobs" / "postings" / "2026-01-01" / "thehub" / "old.json").exists()


def test_import_leaves_the_lock_file_in_place(env):
    archive = _export(env, env.tmp_path / "out.tar.gz")["path"]
    env.dst_jobs.mkdir()
    (env.dst_jobs / ".lock").write_text("")
    (env.dst_jobs / "history.json").write_text("{}")

    result = _import(env, archive)

    assert (env.dst_jobs / ".lock").exists()
    assert not (Path(result["backup_dir"]) / "jobs" / ".lock").exists()


def test_import_keeps_this_computers_usage_log(env):
    from door.core import usage
    archive = _export(env, env.tmp_path / "out.tar.gz")["path"]
    env.dst_jobs.mkdir()
    (env.dst_jobs / usage.LOG_NAME).write_text("{}\n")
    (env.dst_jobs / "history.json").write_text("{}")

    _import(env, archive)

    assert (env.dst_jobs / usage.LOG_NAME).read_text() == "{}\n"


def test_import_holds_the_ledger_lock(env, monkeypatch):
    from door.core.lock import lock_holder

    archive = _export(env, env.tmp_path / "out.tar.gz")["path"]
    seen = {}
    real = archive_core._swap_in

    def spy(*args, **kwargs):
        seen["holder"] = lock_holder(env.dst_jobs)
        return real(*args, **kwargs)

    monkeypatch.setattr(archive_core, "_swap_in", spy)
    _import(env, archive)
    assert seen["holder"]["purpose"] == "import"


def test_import_warns_about_paths_missing_on_this_machine(env):
    config = json.loads((env.profile_dir / "config.json").read_text())
    config["cv_template"] = str(env.tmp_path / "no-such-template.html")
    (env.profile_dir / "config.json").write_text(json.dumps(config))
    archive = _export(env, env.tmp_path / "out.tar.gz")["path"]

    result = _import(env, archive)

    assert any("cv_template" in w for w in result["warnings"])


def _set_plan(profile_dir, path):
    config = json.loads((profile_dir / "config.json").read_text())
    config["claude_config_dir"] = path
    (profile_dir / "config.json").write_text(json.dumps(config))


def test_the_claude_plan_folder_stays_on_its_computer(env):
    """claude_config_dir names a folder of the exporting computer: not in the archive, and an import keeps this computer's."""
    _set_plan(env.profile_dir, "/Users/other/.claude-work")
    archive = _export(env, env.tmp_path / "out.tar.gz")["path"]
    with tarfile.open(archive) as tar:
        packed = json.load(tar.extractfile("profile/config.json"))
    assert "claude_config_dir" not in packed
    assert packed["location"] == "Copenhagen"

    # a computer with no plan folder of its own gets none, and no warning about the other's
    result = _import(env, archive)
    assert "claude_config_dir" not in json.loads((env.dst_profile / "config.json").read_text())
    assert not any("claude_config_dir" in w for w in result["warnings"])

    # a computer with its own keeps it through a second import
    own = str(env.tmp_path / "own-plan")
    (env.tmp_path / "own-plan").mkdir()
    _set_plan(env.dst_profile, own)
    result = _import(env, archive)
    assert json.loads((env.dst_profile / "config.json").read_text())["claude_config_dir"] == own
    assert result["warnings"] == []


def test_import_relative_template_paths_are_not_warned_about(env):
    config = json.loads((env.profile_dir / "config.json").read_text())
    config["cv_content"] = "profile/cv.md"
    (env.profile_dir / "config.json").write_text(json.dumps(config))
    archive = _export(env, env.tmp_path / "out.tar.gz")["path"]

    result = _import(env, archive)

    assert not any("cv_content" in w for w in result["warnings"])


def test_import_missing_archive(env):
    with pytest.raises(FileNotFoundError):
        _import(env, env.tmp_path / "nope.tar.gz")


def test_import_rejects_a_file_that_is_not_an_archive(env):
    junk = env.tmp_path / "junk.tar.gz"
    junk.write_text("not a tarball")
    with pytest.raises(ValueError, match="not an export from The other door"):
        _import(env, junk)


def test_import_rejects_an_archive_without_a_manifest(env):
    archive = _tar_with(env.tmp_path, {"profile/config.json": b"{}"}, manifest=False)
    with pytest.raises(ValueError, match="not an export from The other door"):
        _import(env, archive)


def test_import_rejects_a_newer_format(env):
    path = env.tmp_path / "future.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        data = json.dumps({"format": 99}).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    with pytest.raises(ValueError, match="newer"):
        _import(env, path)


def test_import_rejects_an_archive_without_a_config(env):
    archive = _tar_with(env.tmp_path, {"jobs/applications.json": b"{}"})
    with pytest.raises(ValueError, match="profile/config.json"):
        _import(env, archive)


@pytest.mark.parametrize("member", ["../evil.txt", "/etc/evil", "profile/../../evil", "elsewhere/x.txt"])
def test_import_rejects_members_outside_profile_and_jobs(env, member):
    archive = _tar_with(env.tmp_path, {"profile/config.json": b"{}", member: b"x"})
    with pytest.raises(ValueError, match="unexpected entry"):
        _import(env, archive)
    assert not env.dst_profile.exists()


def test_import_rejects_links(env):
    link = tarfile.TarInfo("profile/cv.md")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    archive = _tar_with(env.tmp_path, {"profile/config.json": b"{}", "profile/cv.md": link})
    with pytest.raises(ValueError, match="unexpected entry"):
        _import(env, archive)


def test_a_rejected_import_touches_nothing(env):
    env.dst_profile.mkdir()
    (env.dst_profile / "cv.md").write_text("# Old CV")
    archive = _tar_with(env.tmp_path, {"profile/config.json": b"{}", "../evil": b"x"})
    with pytest.raises(ValueError):
        _import(env, archive)
    assert (env.dst_profile / "cv.md").read_text() == "# Old CV"
    assert not env.backups_dir.exists()
