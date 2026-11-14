"""The release gate's pieces (#57): the saved data of each release, opened by the current code.

`tests/data_versions/<X.Y.Z>/` holds a release's own `profile/` and `jobs/` and `expected.json`, what that release's
tools read back from them (`scripts/save_release_data.py`). `check` copies one to a temporary home, runs the upgrade
and reads it back with the same tools (`scripts/release_data.py`'s `snapshot`), and names every difference from
`expected.json` that no step of the upgrade lists as intended (`Step.changes`).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

from door.core import migrations, workspace
from paths import REPO_ROOT

SAMPLES_DIR = REPO_ROOT / "tests" / "data_versions"

_spec = importlib.util.spec_from_file_location("release_data", REPO_ROOT / "scripts" / "release_data.py")
release_data = importlib.util.module_from_spec(_spec)
sys.modules["release_data"] = release_data
_spec.loader.exec_module(release_data)


def releases() -> list[Path]:
    """The saved release folders, oldest first."""
    found = [p for p in SAMPLES_DIR.iterdir() if p.is_dir()] if SAMPLES_DIR.is_dir() else []
    return sorted(found, key=lambda p: tuple(int(part) for part in p.name.split(".")))


def listed_changes(folder: Path, steps: list[migrations.Step]) -> list[str]:
    """The paths the steps that will run on *folder*'s data (from its version on) list as changed on purpose."""
    have = migrations.read_version(folder) or migrations.UNVERSIONED
    return [change for step in steps[have.n:] for change in step.changes]


def open_release(sample: Path, home: Path, monkeypatch, *, profile_steps=None, jobs_steps=None):
    """Copy *sample*'s folders to *home*, upgrade them and read them back.

    Returns ``(status, snapshot, changes)``: `migrations.upgrade_all`'s answer (None: upgraded), what the current
    tools read back (normalised), and the changes the steps that ran list.
    """
    for name in ("profile", "jobs"):
        shutil.copytree(sample / name, home / name)
    for name, relative in (("PROFILE_DIR", "profile"), ("JOBS_DIR", "jobs"), ("BACKUPS_DIR", "backups"), ("UPSKILL_DIR", "upskill")):
        monkeypatch.setattr(workspace, name, home / relative)
    monkeypatch.setattr(workspace, "HOME", home)
    monkeypatch.setattr(workspace, "MCP_CONFIG", home / ".mcp.json")
    profile_steps = migrations.PROFILE_STEPS if profile_steps is None else profile_steps
    jobs_steps = migrations.JOBS_STEPS if jobs_steps is None else jobs_steps
    changes = listed_changes(home / "profile", profile_steps) + listed_changes(home / "jobs", jobs_steps)
    status = migrations.upgrade_all(
        home / "profile", home / "jobs", home / "backups", profile_steps=profile_steps, jobs_steps=jobs_steps,
    )
    return status, release_data.snapshot(home), changes


def check(sample: Path, home: Path, monkeypatch, *, profile_steps=None, jobs_steps=None) -> list[str]:
    """Every way the upgraded sample reads back differently from `expected.json` that no step lists, as lines."""
    status, now, changes = open_release(sample, home, monkeypatch, profile_steps=profile_steps, jobs_steps=jobs_steps)
    if status is not None:
        return [f"the data was not upgraded: {status['state']}: {status['message']}"]
    expected = json.loads((sample / "expected.json").read_text(encoding="utf-8"))
    return release_data.unlisted(release_data.differences(expected, now), changes)
