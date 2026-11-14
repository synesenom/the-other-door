"""The inventory of stored files (#56): every file the code writes under profile/ and jobs/ is named in it."""

import json

import pytest

from door.core import stored


@pytest.mark.parametrize("path", [
    "profile/config.json", "profile/fonts/Figtree-Regular.otf", "profile/cv.md.bak", "profile/.data_version",
    "jobs/history.json", "jobs/discovery/linkedin.json", "jobs/runs/2026-01-01T10-00-00.json", "jobs/runs/latest.log",
    "jobs/postings/2026-01-01/jobindex/jobindex.123.json", "jobs/output/jobindex.123/cv.tex",
    "jobs/output/jobindex.123/sent/cv.pdf", "jobs/output/jobindex.123/photo.jpg", "jobs/market/report-2026-01-01.md",
    "jobs/drift/thehub/2026.html", "jobs/.lock",
])
def test_known_paths_are_named(path):
    assert stored.named(path) is not None


@pytest.mark.parametrize("path", ["profile/surprise.json", "jobs/new_ledger.json", "jobs/output/x/y/z.json", "profile/fonts"])
def test_unknown_paths_are_not(path):
    assert stored.named(path) is None


def test_every_pattern_is_unique_and_has_a_model():
    patterns = [e.pattern for e in stored.INVENTORY]
    assert len(patterns) == len(set(patterns))
    assert all(e.model and e.kind for e in stored.INVENTORY)


def test_unnamed_lists_what_the_inventory_misses(tmp_path):
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "config.json").write_text("{}")
    (tmp_path / "profile" / "mystery.bin").write_text("?")
    assert stored.unnamed(tmp_path) == ["profile/mystery.bin"]


def test_cores_store_only_named_files(tmp_path, monkeypatch):
    """A runtime check: representative writers run in a throwaway home leave only inventoried files."""
    from door.commands import companies as companies_cmd
    from door.commands import profile as profile_cmd
    from door.commands import stories as stories_cmd
    from door.core import migrations, tracker, workspace

    profile_dir, jobs_dir = tmp_path / "profile", tmp_path / "jobs"
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(workspace, "BACKUPS_DIR", tmp_path / "backups")

    profile_cmd._init_core({"name": "Ada", "email": "a@x.com", "location": "Copenhagen", "role_targets": ["analyst"]})
    profile_cmd._save_cv_core("# Ada\n\nA CV.\n")
    profile_cmd._save_cv_core("# Ada\n\nA changed CV.\n")  # leaves cv.md.bak
    stories_cmd._save_story_core("A story", "c", "a", "r", "l")
    companies_cmd._add_core(["Acme"], probe=False)
    jobs_dir.mkdir(exist_ok=True)
    ledger = tracker.ApplicationTracker(jobs_dir / "applications.json")
    ledger.set_status("jobindex.1", "applied")
    migrations.upgrade_all(profile_dir, jobs_dir, tmp_path / "backups")

    assert (profile_dir / ".data_version").exists()
    assert stored.unnamed(tmp_path) == []
    assert [p for p in (tmp_path / "profile").rglob("*") if p.is_file()]
