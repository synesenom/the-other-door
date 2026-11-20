"""The release gate's pieces (#57): the saved data of each release, opened by the current code.

`tests/data_versions/<X.Y.Z>/` holds a release's own `profile/` and `jobs/` and `expected.json`, what that release's
tools read back from them (`scripts/save_release_data.py`), and `<X.Y.Z>/default/` the same with the default profile:
no template in `profile/`, `cv_template` and `cover_letter_template` null, as most users have it (#141). 0.2.0's
`default/` checks little: `READ_CHANGES["0.2.0"]` (#146) excuses the template paths of both variants, so the default
profile's template path is really compared from the next release's `default/` sample on. `check` copies one to a temporary home, runs the upgrade
and reads it back with the same tools (`scripts/release_data.py`'s `snapshot`), and names every difference from
`expected.json` that no step of the upgrade lists as intended (`Step.changes`) and no `READ_CHANGES` entry lists as a
change in how the same data is read (#101).
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

# Intended changes in how this code reads old data where the stored shape did not change, so no `Step` exists to list
# them (#101). Keyed by the newest saved release when the read changed: an entry applies to that sample and every older
# one. Each is an exact path into `expected.json` and the PR that changed it; kept until a major bump deletes the
# samples it applies to. `/dev-release`'s `data-migrator` adds them; a `release` test fails for one that covers nothing.
READ_CHANGES: dict[str, tuple[tuple[str, str], ...]] = {
    "0.2.0": (
        # #146: the CV and letter are HTML bodies; a job prepared with LaTeX (cv.tex) is kept and never read, and a
        # `.tex` template is not read (the shipped HTML one is used), so what show and show_profile read back is empty
        *(
            (f"show.jobindex.{job}.materials.{field}", "#146: the CV and letter are HTML bodies; the LaTeX ones are kept, never read")
            for job in ("1002", "1004") for field in ("cover_letter_words", "keywords", "tailoring")
        ),
        ("show.jobindex.1004.materials.unsupported", "#146: the CV and letter are HTML bodies; the LaTeX ones are kept, never read"),
        ("show.jobindex.1002.materials.unsupported", "#484 (#444): a finding is read only for the HTML documents it was checked against; a LaTeX job's are kept, never read"),
        ("show_profile.templates.cover_letter.is_example", "#146: a LaTeX template is not read; the shipped HTML one is used"),
        ("show_profile.templates.cover_letter.path", "#146: a LaTeX template is not read; the shipped HTML one is used"),
        ("show_profile.templates.cv.is_example", "#146: a LaTeX template is not read; the shipped HTML one is used"),
        ("show_profile.templates.cv.path", "#146: a LaTeX template is not read; the shipped HTML one is used"),
    ),
    "0.1.0": (
        ("status_summary.application.ghosted", "#87: no change for 45 days counts as no answer"),
        ("status_summary.application.pending", "#87: no change for 45 days counts as no answer"),
        ("status_summary.pass_rates.application.decided", "#87: no change for 45 days counts as no answer"),
        ("status_summary.pass_rates.application.rate", "#87: no change for 45 days counts as no answer"),
        ("status_summary.pass_rates.application.low", "#87: no change for 45 days counts as no answer"),
        ("status_summary.pass_rates.application.high", "#87: no change for 45 days counts as no answer"),
        ("status_summary.pipeline.above_threshold_by_status.applied", "#87: a match sent then set aside counts as applied"),
        ("status_summary.pipeline.above_threshold_by_status.discarded", "#87: a match sent then set aside counts as applied"),
    ),
}

_spec = importlib.util.spec_from_file_location("release_data", REPO_ROOT / "scripts" / "release_data.py")
release_data = importlib.util.module_from_spec(_spec)
sys.modules["release_data"] = release_data
_spec.loader.exec_module(release_data)


DEFAULT = "default"  # a release's variant with the default profile


def releases() -> list[Path]:
    """The saved release folders, oldest first."""
    found = [p for p in SAMPLES_DIR.iterdir() if p.is_dir()] if SAMPLES_DIR.is_dir() else []
    return sorted(found, key=lambda p: _version(p.name))


def samples() -> list[Path]:
    """Every saved sample the gate opens, oldest release first: each release's own, then its `default/` variant."""
    return [s for release in releases() for s in (release, release / DEFAULT) if (s / "profile").is_dir()]


def _release(sample: Path) -> str:
    """The version a sample was saved from: its folder's name, or its release's for a `default/` variant."""
    return sample.parent.name if sample.name == DEFAULT else sample.name


def _version(name: str) -> tuple[int, ...]:
    return tuple(int(part) for part in name.split("."))


def read_changes(sample: Path) -> list[str]:
    """The `READ_CHANGES` paths that apply to *sample*: every entry keyed by its release or a newer one."""
    have = _version(_release(sample))
    return [path for key, entries in READ_CHANGES.items() if _version(key) >= have for path, _ in entries]


def listed_changes(folder: Path, steps: list[migrations.Step]) -> list[str]:
    """The paths the steps that will run on *folder*'s data (from its version on) list as changed on purpose."""
    have = migrations.read_version(folder) or migrations.UNVERSIONED
    return [change for step in steps[have.n:] for change in step.changes]


def sample_major(sample: Path) -> int:
    """The major version of the release a sample was saved from (its folder is named `X.Y.Z`)."""
    return int(_release(sample).split(".")[0])


def is_older_major(sample: Path) -> bool:
    """A sample of an earlier major: this build refuses it (`old_major`) until `/dev-release` deletes it after the tag."""
    return sample_major(sample) < migrations.app_major()


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def open_release(sample: Path, home: Path, monkeypatch, *, profile_steps=None, jobs_steps=None, read_back=True):
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
    return status, release_data.snapshot(home) if read_back else None, changes


def check_refused(sample: Path, home: Path, monkeypatch, *, profile_steps=None, jobs_steps=None) -> list[str]:
    """A sample of an older major must be refused as `old_major` and left exactly as it was: lines for what is not."""
    status, _, _ = open_release(
        sample, home, monkeypatch, profile_steps=profile_steps, jobs_steps=jobs_steps, read_back=False,
    )
    found = []
    if status is None or status["state"] != "old_major":
        found.append(f"expected the data to be refused as old_major, got {status}")
    for name in ("profile", "jobs"):
        before, after = _tree(sample / name), _tree(home / name)
        if before != after:
            changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
            found.append(f"{name}/ was changed although it was refused: {', '.join(changed)}")
    return found


def check(sample: Path, home: Path, monkeypatch, *, profile_steps=None, jobs_steps=None) -> list[str]:
    """Every way the upgraded sample reads back differently from `expected.json` that no step lists, as lines.

    A sample of an older major is not upgraded: it must be refused and untouched (`check_refused`)."""
    if is_older_major(sample):
        return check_refused(sample, home, monkeypatch, profile_steps=profile_steps, jobs_steps=jobs_steps)
    status, now, changes = open_release(sample, home, monkeypatch, profile_steps=profile_steps, jobs_steps=jobs_steps)
    if status is not None:
        return [f"the data was not upgraded: {status['state']}: {status['message']}"]
    expected = json.loads((sample / "expected.json").read_text(encoding="utf-8"))
    return release_data.unlisted(release_data.differences(expected, now), changes + read_changes(sample))
