"""The postings live in `jobs/postings/<YYYY-MM-DD>/<site>/`, apart from the ledgers, and day
folders left directly under `jobs/` by an older version are moved there."""

import json

from door.core import selection, workspace
from door.core.lock import ledger_lock


def _old_day(jobs_dir, day="2026-07-01", site="jobindex", name="a.json", data=None):
    folder = jobs_dir / day / site
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(data or {"id": name}), encoding="utf-8")
    return folder / name


def test_a_day_folder_is_under_postings(tmp_path):
    assert workspace.postings_dir(tmp_path) == tmp_path / "postings"
    assert workspace.day_dir(tmp_path, "2026-07-01") == tmp_path / "postings" / "2026-07-01"


def test_old_day_folders_move_under_postings(tmp_path):
    _old_day(tmp_path)
    (tmp_path / "output" / "x").mkdir(parents=True)
    (tmp_path / "runs").mkdir()

    assert workspace.move_day_folders(tmp_path) == 1

    assert (tmp_path / "postings" / "2026-07-01" / "jobindex" / "a.json").exists()
    assert not (tmp_path / "2026-07-01").exists()
    assert (tmp_path / "output" / "x").is_dir() and (tmp_path / "runs").is_dir()


def test_moving_is_idempotent_and_needs_no_jobs_dir(tmp_path):
    assert workspace.move_day_folders(tmp_path / "missing") == 0
    _old_day(tmp_path)
    workspace.move_day_folders(tmp_path)
    assert workspace.move_day_folders(tmp_path) == 0


def test_a_day_on_both_sides_is_merged_keeping_the_new_files(tmp_path):
    _old_day(tmp_path, name="old.json")
    _old_day(tmp_path, name="both.json", data={"id": "both", "v": "old"})
    new = workspace.day_dir(tmp_path, "2026-07-01") / "jobindex"
    new.mkdir(parents=True)
    (new / "both.json").write_text(json.dumps({"id": "both", "v": "new"}), encoding="utf-8")

    workspace.move_day_folders(tmp_path)

    assert (new / "old.json").exists()
    assert json.loads((new / "both.json").read_text())["v"] == "new"


def test_date_dirs_reads_postings_and_moves_old_folders_first(tmp_path):
    _old_day(tmp_path, day="2026-07-01")
    (workspace.day_dir(tmp_path, "2026-07-02") / "thehub").mkdir(parents=True)

    assert selection.date_dirs(tmp_path) == [workspace.day_dir(tmp_path, d) for d in ("2026-07-01", "2026-07-02")]


def test_taking_the_ledger_lock_moves_old_folders(tmp_path):
    _old_day(tmp_path)
    with ledger_lock(tmp_path, "test"):
        assert (workspace.day_dir(tmp_path, "2026-07-01") / "jobindex" / "a.json").exists()


# --------------------------------------------------------------------------- #
# DOOR_HOME (#216)
# --------------------------------------------------------------------------- #

import importlib
import sys

import pytest


@pytest.fixture
def reloaded(monkeypatch):
    """``reloaded(home)`` re-imports `workspace` with DOOR_HOME set (or unset); undone on teardown."""
    def _reload(home=None):
        if home is None:
            monkeypatch.delenv("DOOR_HOME", raising=False)
        else:
            monkeypatch.setenv("DOOR_HOME", str(home))
        return importlib.reload(workspace)

    yield _reload
    monkeypatch.undo()
    importlib.reload(workspace)


def test_default_home_is_the_checkout(reloaded):
    for value in (None, ""):
        ws = reloaded(None) if value is None else reloaded("")
        assert ws.HOME == ws.REPO_ROOT
        assert ws.PROFILE_DIR == ws.REPO_ROOT / "profile"
        assert ws.JOBS_DIR == ws.REPO_ROOT / "jobs"
        assert ws.BACKUPS_DIR == ws.REPO_ROOT / "backups"
        assert ws.UPSKILL_DIR == ws.REPO_ROOT / "upskill"
        assert ws.MCP_CONFIG == ws.REPO_ROOT / ".mcp.json"


def test_door_home_moves_the_data_dirs_only(reloaded, tmp_path):
    ws = reloaded(tmp_path)
    home = tmp_path.resolve()
    assert ws.HOME == home
    assert ws.PROFILE_DIR == home / "profile"
    assert ws.JOBS_DIR == home / "jobs"
    assert ws.BACKUPS_DIR == home / "backups"
    assert ws.UPSKILL_DIR == home / "upskill"
    assert ws.MCP_CONFIG == home / ".mcp.json"
    assert ws.PROFILE_EXAMPLE_DIR == ws.REPO_ROOT / "profile.example"
    assert home != ws.REPO_ROOT


def test_mcp_config_entry_names_this_interpreter(reloaded, tmp_path):
    ws = reloaded(tmp_path)
    entry = ws.mcp_config_entry()["mcpServers"]["door"]
    assert entry["command"] == sys.executable
    assert entry["args"] == ["-m", "door.mcp_server"]
    assert str(ws.REPO_ROOT / "src") in entry["env"]["PYTHONPATH"].split(__import__("os").pathsep)
    assert entry["env"]["DOOR_HOME"] == str(ws.HOME)


def test_mcp_config_entry_carries_the_bundled_bin(reloaded, tmp_path, monkeypatch):
    # The tailor's own MCP server must find the bundled Tectonic too (#223).
    monkeypatch.setenv("DOOR_BIN", "/bundle/bin")
    assert reloaded(tmp_path).mcp_config_entry()["mcpServers"]["door"]["env"]["DOOR_BIN"] == "/bundle/bin"
    monkeypatch.delenv("DOOR_BIN")
    assert "DOOR_BIN" not in reloaded(tmp_path).mcp_config_entry()["mcpServers"]["door"]["env"]


def test_a_checkout_is_told_by_its_pyproject(reloaded, tmp_path, monkeypatch):
    ws = reloaded(None)
    assert ws.is_checkout() is True
    monkeypatch.setattr(ws, "REPO_ROOT", tmp_path)
    assert ws.is_checkout() is False


def test_ensure_mcp_config_leaves_the_checkout_alone(reloaded):
    ws = reloaded(None)
    assert ws.ensure_mcp_config() == ws.REPO_ROOT / ".mcp.json"


def test_ensure_mcp_config_writes_idempotently_and_rewrites_stale(reloaded, tmp_path):
    ws = reloaded(tmp_path)
    path = ws.ensure_mcp_config()
    assert path == tmp_path.resolve() / ".mcp.json"
    assert json.loads(path.read_text()) == ws.mcp_config_entry()
    mtime = path.stat().st_mtime_ns
    ws.ensure_mcp_config()
    assert path.stat().st_mtime_ns == mtime

    stale = ws.mcp_config_entry()
    stale["mcpServers"]["door"]["command"] = "/old/python"
    path.write_text(json.dumps(stale))
    ws.ensure_mcp_config()
    assert json.loads(path.read_text()) == ws.mcp_config_entry()

    stale["mcpServers"]["door"]["command"] = sys.executable
    stale["mcpServers"]["door"]["env"]["PYTHONPATH"] = "/elsewhere"
    path.write_text(json.dumps(stale))
    ws.ensure_mcp_config()
    assert json.loads(path.read_text()) == ws.mcp_config_entry()
    assert not list(tmp_path.glob(".mcp.json.*"))


def test_ensure_mcp_config_in_a_read_only_home_names_the_variable(reloaded, tmp_path, monkeypatch):
    ws = reloaded(tmp_path)

    def boom(*a, **k):
        raise PermissionError("read-only")
    monkeypatch.setattr(ws.os, "replace", boom)
    with pytest.raises(RuntimeError, match="DOOR_HOME"):
        ws.ensure_mcp_config()
