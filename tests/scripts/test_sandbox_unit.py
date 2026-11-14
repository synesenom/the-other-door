"""Unit tests for scripts/sandbox.py: the real CLI against a throwaway profile.

`/dev-add-country`'s validator runs the new country's boards for real with a fake
profile; the sandbox must never read or write the repo's own profile/ and jobs/, nor
reach Google Drive.
"""

import importlib.util

import pytest

from door.core import lock, workspace
from paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("sandbox", REPO_ROOT / "scripts" / "sandbox.py")
sandbox = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sandbox)


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    """`install` sets module globals; put them back after each test."""
    for module, name in [(workspace, "PROFILE_DIR"), (workspace, "JOBS_DIR"), (workspace, "HOME"),
                         (workspace, "BACKUPS_DIR"), (workspace, "UPSKILL_DIR"), (workspace, "MCP_CONFIG"),
                         (lock, "pre_acquire_hook"), (lock, "post_release_hook")]:
        monkeypatch.setattr(module, name, getattr(module, name))


def test_install_points_the_workspace_at_the_sandbox(tmp_path):
    sandbox.install(tmp_path)

    assert workspace.PROFILE_DIR == tmp_path / "profile"
    assert workspace.JOBS_DIR == tmp_path / "jobs"
    assert workspace.HOME == tmp_path
    assert workspace.BACKUPS_DIR == tmp_path / "backups"
    assert workspace.UPSKILL_DIR == tmp_path / "upskill"
    assert workspace.MCP_CONFIG == tmp_path / ".mcp.json"


def test_install_seeds_the_profile_from_the_example_once(tmp_path):
    sandbox.install(tmp_path)
    assert (tmp_path / "profile" / "config.json").read_text() == (
        workspace.PROFILE_EXAMPLE_DIR / "config.json").read_text()

    (tmp_path / "profile" / "config.json").write_text("{}")
    sandbox.install(tmp_path)
    assert (tmp_path / "profile" / "config.json").read_text() == "{}"


def test_install_stamps_both_folders_with_the_current_data_versions(tmp_path):
    """A seeded folder with data and no version file reads as v0.1.0's and is upgraded (backed up) at the first start."""
    from door.core import migrations

    sandbox.install(tmp_path)
    assert (tmp_path / "profile" / ".data_version").read_text() == f"{migrations.current('profile')}\n"
    assert (tmp_path / "jobs" / ".data_version").read_text() == f"{migrations.current('jobs')}\n"


def test_install_turns_the_drive_sync_off(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(lock, "pre_acquire_hook", lambda *a: calls.append(a))
    monkeypatch.setattr(lock, "post_release_hook", lambda *a: calls.append(a))

    sandbox.install(tmp_path)
    lock.pre_acquire_hook("find", tmp_path / "jobs")
    lock.post_release_hook("find", tmp_path / "jobs")

    assert calls == []


def test_main_runs_the_cli_inside_the_sandbox(tmp_path, monkeypatch):
    seen = {}

    def fake_cli(args, prog_name, standalone_mode):
        seen.update(args=args, profile=workspace.PROFILE_DIR, jobs=workspace.JOBS_DIR)
        return 0

    monkeypatch.setattr(sandbox, "_cli", lambda: fake_cli)

    assert sandbox.main([str(tmp_path), "find", "search", "--boards", "jobindex"]) == 0
    assert seen == {"args": ["find", "search", "--boards", "jobindex"],
                    "profile": tmp_path / "profile", "jobs": tmp_path / "jobs"}
