"""`export` / `import`: carry profile/ and jobs/ to another computer as one archive.

The archive never holds the ledger lock;
`import` replaces the local data after moving it to a timestamped backup.
"""

import io
import json
import tarfile
import types
from pathlib import Path

import pytest
from click.testing import CliRunner

from door.cli import cli
from door.commands import archive as archive_cmd
from door.core import migrations, workspace
import door.mcp_server as server
from profile_utils import write_config
from cli_utils import result_text


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
    return archive_cmd._export_core(path, profile_dir=env.profile_dir, jobs_dir=env.jobs_dir)


def _import(env, archive):
    return archive_cmd._import_core(
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
        archive_cmd._export_core(tmp_path / "x.tar.gz", profile_dir=tmp_path / "none", jobs_dir=env.jobs_dir)


def test_export_works_without_jobs(env, tmp_path):
    result = archive_cmd._export_core(tmp_path / "x.tar.gz", profile_dir=env.profile_dir, jobs_dir=tmp_path / "nojobs")
    assert {n for n in _names(result["path"]) if n.startswith("jobs/")} <= {"jobs/", "jobs/.data_version"}  # the lock stamps it


def test_export_holds_the_ledger_lock(env, monkeypatch):
    from door.core.lock import lock_holder

    seen = {}
    real = archive_cmd._add_tree

    def spy(tar, root, arcname, exclude):
        seen["holder"] = lock_holder(env.jobs_dir)
        return real(tar, root, arcname, exclude)

    monkeypatch.setattr(archive_cmd, "_add_tree", spy)
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
    real = archive_cmd._swap_in

    def spy(*args, **kwargs):
        seen["holder"] = lock_holder(env.dst_jobs)
        return real(*args, **kwargs)

    monkeypatch.setattr(archive_cmd, "_swap_in", spy)
    _import(env, archive)
    assert seen["holder"]["purpose"] == "import"


def test_import_warns_about_paths_missing_on_this_machine(env):
    config = json.loads((env.profile_dir / "config.json").read_text())
    config["cv_template"] = str(env.tmp_path / "no-such-template.tex")
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


# --------------------------------------------------------------------------- #
# CLI and MCP
# --------------------------------------------------------------------------- #

def _line(text: str, needle: str) -> str:
    return next(line for line in text.splitlines() if needle in line)


def _row_path(text: str, label: str) -> Path:
    """The path on the ``  <label>   <path>`` line, resolved (it is shown relative to the cwd)."""
    return Path(_line(text, label).split(None, 1)[1].strip()).resolve()


def test_export_cli(env):
    target = env.tmp_path / "out.tar.gz"
    result = CliRunner().invoke(cli, ["data", "export", str(target)])
    assert result.exit_code == 0, result_text(result)
    out = result.output
    assert _line(out, "Exported").lstrip().startswith("✓")
    files = len(_names(target)) - 1
    assert str(files) in _line(out, "Files")
    assert "KB" in _line(out, "Size")  # a small archive is not "0.0 MB"
    assert _row_path(out, "Archive") == target.resolve()  # one unbroken, copyable path
    next_line = _line(out, "Next")
    assert "./door data import out.tar.gz" in next_line and "other computer" in next_line
    assert "\x1b[" not in out


def test_export_cli_errors_cleanly(env):
    (env.tmp_path / "out.tar.gz").write_text("x")
    result = CliRunner().invoke(cli, ["data", "export", str(env.tmp_path / "out.tar.gz")])
    assert result.exit_code == 1
    assert "already exists" in result_text(result)


def test_import_cli(env, monkeypatch):
    _versioned(env)
    archive = _export(env, env.tmp_path / "out.tar.gz")["path"]
    monkeypatch.setattr(workspace, "PROFILE_DIR", env.dst_profile)
    monkeypatch.setattr(workspace, "JOBS_DIR", env.dst_jobs)
    env.dst_profile.mkdir()
    (env.dst_profile / "cv.md").write_text("# Old CV")

    result = CliRunner().invoke(cli, ["data", "import", str(archive)])

    assert result.exit_code == 0, result_text(result)
    assert (env.dst_profile / "cv.md").read_text() == "# My CV"
    out = result.stdout
    assert _line(out, "Imported").lstrip().startswith("✓") and "out.tar.gz" in _line(out, "Imported")
    [backup] = list(env.backups_dir.iterdir())
    assert _row_path(out, "Backup") == backup.resolve()  # one unbroken, copyable path
    assert "previous data" in out
    assert "\x1b[" not in out
    assert result.stderr == ""


def test_import_cli_warns_on_stderr(env, monkeypatch):
    config = json.loads((env.profile_dir / "config.json").read_text())
    config["cv_template"] = str(env.tmp_path / "no-such-template.tex")
    (env.profile_dir / "config.json").write_text(json.dumps(config))
    archive = _export(env, env.tmp_path / "out.tar.gz")["path"]
    monkeypatch.setattr(workspace, "PROFILE_DIR", env.dst_profile)
    monkeypatch.setattr(workspace, "JOBS_DIR", env.dst_jobs)

    result = CliRunner().invoke(cli, ["data", "import", str(archive)])

    assert result.exit_code == 0, result_text(result)
    warning = _line(result.stderr, "cv_template")
    assert warning.lstrip().startswith("⚠")
    assert "cv_template" not in result.stdout
    assert "Backup" not in result.stdout  # nothing was there to back up


def test_import_cli_errors_cleanly(env):
    result = CliRunner().invoke(cli, ["data", "import", str(env.tmp_path / "nope.tar.gz")])
    assert result.exit_code == 1
    assert "Error:" in result_text(result)


def test_export_and_import_tools(env, monkeypatch):
    from door.core import path_scope

    monkeypatch.setenv(path_scope.ENV, "1")  # the archive lives outside the data folder, as the app's dialogs allow
    assert server.CLI_COMMAND_TOOLS["data export"] == ("export_data",)
    assert server.CLI_COMMAND_TOOLS["data import"] == ("import_data",)

    exported = server.export_data(path=str(env.tmp_path / "out.tar.gz"))
    assert exported["path"] == str(env.tmp_path / "out.tar.gz")

    monkeypatch.setattr(workspace, "PROFILE_DIR", env.dst_profile)
    monkeypatch.setattr(workspace, "JOBS_DIR", env.dst_jobs)
    imported = server.import_data(archive=exported["path"])
    assert (env.dst_profile / "cv.md").read_text() == "# My CV"
    assert imported["backup_dir"] is None

    assert "error" in server.import_data(archive=str(env.tmp_path / "nope.tar.gz"))
    assert "already exists" in server.export_data(path=exported["path"])["error"]


# --------------------------------------------------------------------------- Google Drive (#265)
from door.core import drive, sync  # noqa: E402


def test_export_leaves_the_progress_mirror_out(env):
    (env.jobs_dir / ".progress.json").write_text("{}")
    assert "jobs/.progress.json" not in _names(_export(env, env.tmp_path / "out.tar.gz")["path"])


def test_export_leaves_the_usage_log_out(env):
    """The usage log (#575) describes this computer's Claude calls; it is not moved with the data."""
    from door.core import usage
    (env.jobs_dir / usage.LOG_NAME).write_text("{}\n")
    assert f"jobs/{usage.LOG_NAME}" not in _names(_export(env, env.tmp_path / "out.tar.gz")["path"])


class _FakeDrive:
    def __init__(self, monkeypatch):
        self.blob, self.version, self.uploads = None, 0, 0
        monkeypatch.setattr(drive, "remote_meta", lambda: None if self.blob is None else {"id": "A", "version": str(self.version), "properties": {}})
        monkeypatch.setattr(drive, "download", lambda dest: Path(dest).write_bytes(self.blob))
        monkeypatch.setattr(drive, "upload", self._upload)

    def _upload(self, src, properties=None):
        self.blob = Path(src).read_bytes()
        self.version += 1
        self.uploads += 1
        return str(self.version)


@pytest.fixture
def connected(env, monkeypatch):
    drive.write_state({"refresh_token": "rt", "account": "me@x.org"})
    return _FakeDrive(monkeypatch)


def test_connect_command_prints_the_account(env, monkeypatch):
    monkeypatch.setattr(drive, "connect", lambda **kw: {"account": "me@x.org"})
    result = CliRunner().invoke(cli, ["data", "connect"])
    assert result.exit_code == 0, result_text(result)
    assert "me@x.org" in result_text(result)


def test_connect_command_prints_the_link_and_the_private_window_hint(env, monkeypatch):
    def fake_connect(show_url=None, **kw):
        show_url("https://accounts.google.com/o/oauth2/v2/auth?x=1")
        return {"account": "me@x.org"}

    monkeypatch.setattr(drive, "connect", fake_connect)
    result = CliRunner().invoke(cli, ["data", "connect"])
    text = result_text(result)
    assert result.exit_code == 0, text
    assert "https://accounts.google.com/o/oauth2/v2/auth?x=1" in text
    assert "private window" in text


def test_connect_command_fails_plainly_when_unconfigured(env):
    result = CliRunner().invoke(cli, ["data", "connect"])
    assert result.exit_code != 0
    assert "not configured in this build" in result_text(result)


def test_sync_pushes_then_reports_nothing_to_do(env, connected):
    runner = CliRunner()
    first = runner.invoke(cli, ["data", "sync"])
    assert first.exit_code == 0, result_text(first)
    assert connected.uploads == 1
    second = runner.invoke(cli, ["data", "sync"])
    assert second.exit_code == 0 and connected.uploads == 1
    assert "in step" in result_text(second).lower() or "nothing" in result_text(second).lower()


def test_sync_refuses_both_flags(env, connected):
    result = CliRunner().invoke(cli, ["data", "sync", "--keep-local", "--keep-drive"])
    assert result.exit_code != 0
    assert connected.uploads == 0


def test_sync_conflict_names_both_options_and_exits_non_zero(env, connected):
    runner = CliRunner()
    runner.invoke(cli, ["data", "sync"])
    connected.version += 1
    (env.jobs_dir / "mine.json").write_text("x")
    result = runner.invoke(cli, ["data", "sync"])
    assert result.exit_code != 0
    text = result_text(result)
    assert "--keep-local" in text and "--keep-drive" in text
    runner.invoke(cli, ["data", "sync", "--keep-local"])
    assert connected.uploads == 2


def test_sync_when_not_connected(env):
    result = CliRunner().invoke(cli, ["data", "sync"])
    assert result.exit_code != 0
    assert "data connect" in result_text(result)


def test_disconnect_removes_the_state(env, connected, monkeypatch):
    monkeypatch.setattr(drive, "disconnect", lambda: (drive.clear_state(), True)[1])
    result = CliRunner().invoke(cli, ["data", "disconnect"])
    assert result.exit_code == 0
    assert drive.read_state() is None


def test_the_cores_return_dicts_and_never_print(env, connected, monkeypatch, capsys):
    monkeypatch.setattr(drive, "connect", lambda **kw: {"account": "me@x.org"})
    assert archive_cmd._connect_core()["account"] == "me@x.org"
    assert archive_cmd._sync_core()["action"] == "push"
    monkeypatch.setattr(drive, "disconnect", lambda: True)
    assert archive_cmd._disconnect_core() == {"disconnected": True}
    assert capsys.readouterr().out == ""


def test_a_locked_core_pulls_first_and_pushes_after(env, connected, enable_sync_hooks):
    from door.commands import _common as common
    from door.core.lock import ledger_lock

    archive_cmd._sync_core()
    assert connected.uploads == 1
    with ledger_lock(env.jobs_dir, "set_status"):
        (env.jobs_dir / "applications.json").write_text('{"jobindex-acme-ds": {"status": "interview"}}')
    assert connected.uploads == 2
    # the other computer's change is pulled before the next write
    connected.version += 1
    with ledger_lock(env.jobs_dir, "set_status"):
        pass
    assert drive.read_state()["synced_version"] == str(connected.version)
    assert common  # imported to prove the commands layer loads with the hooks on


def test_a_conflict_refuses_a_locked_core(env, connected, enable_sync_hooks):
    from door.core.lock import SyncConflict, ledger_lock

    archive_cmd._sync_core()
    connected.version += 1
    (env.jobs_dir / "mine.json").write_text("x")
    with pytest.raises(SyncConflict):
        with ledger_lock(env.jobs_dir, "set_status"):
            pytest.fail("the block must not run")


# --------------------------------------------------------------------------- #
# data versions (#56)
# --------------------------------------------------------------------------- #
def _versioned(env, profile="0.1", jobs="0.0"):
    (env.profile_dir / ".data_version").write_text(profile)
    (env.jobs_dir / ".data_version").write_text(jobs)


def _tree_bytes(root):
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name not in (".lock", ".lock.json")
    }


def _newer_archive(env, **members):
    entries = {"profile/config.json": b"{}", "profile/cv.md": b"# new", **members}
    return _tar_with(env.tmp_path, entries)


def test_export_carries_the_data_versions(env):
    _versioned(env)
    result = _export(env, env.tmp_path / "out.tar.gz")
    assert {"profile/.data_version", "jobs/.data_version"} <= _names(result["path"])


@pytest.mark.parametrize("member", ["profile/.data_version", "jobs/.data_version"])
def test_a_newer_archive_is_refused_before_anything_changes(env, member):
    from door.core import migrations

    env.dst_profile.mkdir()
    (env.dst_profile / "cv.md").write_text("# Old CV")
    env.dst_jobs.mkdir()
    (env.dst_jobs / "applications.json").write_text("{}")
    before = (_tree_bytes(env.dst_profile), _tree_bytes(env.dst_jobs))
    archive = _newer_archive(env, **{member: b"0.99"})

    with pytest.raises(migrations.RefusedData, match="newer version of The other door"):
        _import(env, archive)

    assert (_tree_bytes(env.dst_profile), _tree_bytes(env.dst_jobs)) == before
    assert not env.backups_dir.exists()
    assert not list(env.dst_profile.parent.glob(".door-import-*"))


def test_an_archive_of_an_older_major_is_refused_before_anything_changes(env, monkeypatch):
    from door import version
    from door.core import migrations

    monkeypatch.setattr(version, "VERSION", "1.0.0")
    env.dst_profile.mkdir()
    (env.dst_profile / "cv.md").write_text("# Old CV")
    archive = _newer_archive(env, **{"profile/.data_version": b"0.1"})

    with pytest.raises(migrations.RefusedData, match=r"The other door 0\.x") as caught:
        _import(env, archive)

    assert caught.value.state == "old_major"
    assert (env.dst_profile / "cv.md").read_text() == "# Old CV"
    assert not env.backups_dir.exists()


def test_a_garbled_version_member_is_refused(env):
    from door.core import migrations

    archive = _newer_archive(env, **{"profile/.data_version": b"banana"})
    with pytest.raises(migrations.RefusedData):
        _import(env, archive)
    assert not env.dst_profile.exists()


def test_an_older_archive_is_upgraded_right_after_the_import(env, monkeypatch):
    from door.core import migrations

    step = migrations.Step("tag", lambda folder: (folder / "tag.done").write_text("x"))
    monkeypatch.setattr(migrations, "PROFILE_STEPS", [step])
    monkeypatch.setattr(migrations, "_state", None)
    archive = _tar_with(env.tmp_path, {"profile/config.json": b"{}"})

    result = _import(env, archive)

    assert (env.dst_profile / ".data_version").read_text().strip() == "0.1"
    assert (env.dst_profile / "tag.done").is_file()
    assert any(p.name.startswith("upgrade-profile-0.0-0.1") for p in env.backups_dir.iterdir())
    assert not any("FAILED" in w or "could not be upgraded" in w for w in result["warnings"])


def test_a_failing_step_after_import_is_one_warning(env, monkeypatch):
    from door.core import migrations

    def boom(folder):
        raise RuntimeError("boom")

    monkeypatch.setattr(migrations, "PROFILE_STEPS", [migrations.Step("explode", boom)])
    monkeypatch.setattr(migrations, "_state", None)
    archive = _tar_with(env.tmp_path, {"profile/config.json": b"{}", "profile/cv.md": b"# imported"})

    result = _import(env, archive)

    failed = [w for w in result["warnings"] if "could not be upgraded" in w]
    assert len(failed) == 1 and "explode" in failed[0]
    assert (env.dst_profile / "cv.md").read_text() == "# imported"
    assert migrations.status()["state"] == "failed"
    monkeypatch.setattr(migrations, "_state", None)


def test_sync_prints_the_warnings_of_a_pull(env, monkeypatch):
    from door.commands import archive

    monkeypatch.setattr(
        archive, "_sync_core", lambda *a, **k: {"action": "pull", "warnings": ["Your data could not be upgraded: step x"]},
    )
    result = CliRunner().invoke(cli, ["data", "sync"])
    assert result.exit_code == 0, result_text(result)
    assert "could not be upgraded" in result_text(result)
