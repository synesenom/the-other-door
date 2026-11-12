"""scripts/migrate_job_ids.py: re-key an existing `jobs/` to the `<site>.<platform_id>` job id (#313)."""

import hashlib
import importlib.util
import json
import types
from pathlib import Path

import pytest

from door.commands import archive as archive_cmd
from door.core import lock, selection, workspace
from door.core.history import HistoryStore
from paths import REPO_ROOT
from profile_utils import write_config

_spec = importlib.util.spec_from_file_location("migrate_job_ids", REPO_ROOT / "scripts" / "migrate_job_ids.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

OLD_DS = "jobindex.acme.data-scientist"  # two postings share it: h1 and h2


def _posting(old_id, site, pid, *, day, title="Data Scientist", company="Acme", url=None, **extra):
    return {
        "id": old_id, "title": title, "company": company, "location": "Copenhagen",
        "url": url or f"https://example.com/{pid}", "description": "d", "source": site,
        "scraped_at": f"{day}T10:00:00Z", "platform_id": pid, **extra,
    }


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _history_entry(job_id, site, url="u"):
    return {"job_id": job_id, "url": url, "source": site, "first_seen": "2026-10-01T00:00:00+00:00",
            "last_seen": "2026-10-02T00:00:00+00:00", "status": "seen"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    profile_dir, jobs_dir = tmp_path / "profile", tmp_path / "jobs"
    profile_dir.mkdir()
    write_config(profile_dir, {"role_targets": ["x"], "location": "Copenhagen"})
    day1, day2 = jobs_dir / "postings" / "2026-10-01", jobs_dir / "postings" / "2026-10-02"
    _write(day1 / "jobindex" / f"{OLD_DS}.json", _posting(OLD_DS, "jobindex", "h1", day="2026-10-01"))
    _write(day2 / "jobindex" / f"{OLD_DS}.json", _posting(OLD_DS, "jobindex", "h2", day="2026-10-02"))
    _write(day2 / "jobindex" / "jobindex.beta.ds.json",
           _posting("jobindex.beta.ds", "jobindex", "h3", day="2026-10-02", company="Beta", duplicate_of=OLD_DS))
    _write(day2 / "teamtailor" / "teamtailor.acme.engineer.json",
           _posting("teamtailor.acme.engineer", "teamtailor", "555", day="2026-10-02", title="Engineer",
                    url="https://acme.teamtailor.com/jobs/555-eng"))
    out = jobs_dir / "output" / OLD_DS
    _write(out / "posting.json", _posting(OLD_DS, "jobindex", "h2", day="2026-10-02"))
    (out / "cv.pdf").write_bytes(b"%PDF")
    (out / "sent").mkdir()
    (out / "sent" / "cv.tex").write_text("sent cv")
    _write(jobs_dir / "applications.json", {OLD_DS: {"status": "applied", "updated_at": "x", "history": []}})
    _write(jobs_dir / "history.json", {
        "h1": _history_entry(OLD_DS, "jobindex"),
        "h2": _history_entry(OLD_DS, "jobindex"),
        "h3": _history_entry("jobindex.beta.ds", "jobindex"),
        "555": _history_entry("teamtailor.acme.engineer", "teamtailor", "https://acme.teamtailor.com/jobs/555-eng"),
        "9999": _history_entry("teamtailor.acme.old", "teamtailor", "https://acme.teamtailor.com/jobs/9999-old"),
        "h-only": _history_entry("jobindex.gone.job", "jobindex"),
    })
    _write(jobs_dir / "last_list.json", {"ranks": {"1": OLD_DS}})
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(workspace, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.chdir(tmp_path)
    return types.SimpleNamespace(tmp_path=tmp_path, profile_dir=profile_dir, jobs_dir=jobs_dir,
                                 backups_dir=tmp_path / "backups")


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in (".lock", ".lock.json"):
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _load(path: Path):
    return json.loads(path.read_text())


def _migrate(env, **kw):
    return script.migrate(jobs_dir=env.jobs_dir, backups_dir=env.backups_dir, **kw)


def test_posting_files_are_renamed_and_their_id_rewritten(env):
    _migrate(env)
    day1, day2 = env.jobs_dir / "postings" / "2026-10-01", env.jobs_dir / "postings" / "2026-10-02"
    assert [p.name for p in (day1 / "jobindex").iterdir()] == ["jobindex.h1.json"]
    assert sorted(p.name for p in (day2 / "jobindex").iterdir()) == ["jobindex.h2.json", "jobindex.h3.json"]
    for path in env.jobs_dir.glob("postings/*/*/*.json"):
        assert _load(path)["id"] == path.stem


def test_per_tenant_postings_get_the_host_in_their_platform_id(env):
    _migrate(env)
    path = env.jobs_dir / "postings" / "2026-10-02" / "teamtailor" / "teamtailor.acme-teamtailor-com-555.json"
    assert _load(path)["platform_id"] == "acme.teamtailor.com-555"
    history = _load(env.jobs_dir / "history.json")
    assert history["teamtailor.acme-teamtailor-com-555"]["platform_id"] == "acme.teamtailor.com-555"
    # a history-only entry takes its host from the history url
    assert history["teamtailor.acme-teamtailor-com-9999"]["platform_id"] == "acme.teamtailor.com-9999"


def test_a_migrated_history_key_equals_what_the_scraper_now_produces(env):
    from door.scrapers.feeds import teamtailor

    item = {"id": "uuid", "title": "Engineer", "url": "https://acme.teamtailor.com/jobs/555-eng",
            "_jobposting": {"identifier": {"value": 555}}}
    from datetime import datetime, timezone
    produced = teamtailor._to_posting(item, "Acme", datetime(2026, 1, 1, tzinfo=timezone.utc))
    _migrate(env)
    assert produced["id"] in _load(env.jobs_dir / "history.json")


def test_history_is_keyed_by_job_id_with_platform_id(env):
    result = _migrate(env)
    history = _load(env.jobs_dir / "history.json")
    assert set(history) == {"jobindex.h1", "jobindex.h2", "jobindex.h3", "jobindex.h-only",
                            "teamtailor.acme-teamtailor-com-555", "teamtailor.acme-teamtailor-com-9999"}
    assert history["jobindex.h1"]["job_id"] == "jobindex.h1" and history["jobindex.h1"]["platform_id"] == "h1"
    assert history["jobindex.h-only"]["platform_id"] == "h-only"  # no posting file
    assert result["history"] == 6
    store = HistoryStore(env.jobs_dir / "history.json")
    assert store.known_ids("jobindex", None) == {"h1", "h2", "h3", "h-only"}


def test_the_ledger_entry_and_output_folder_follow_the_posting_the_output_holds(env):
    result = _migrate(env)
    assert list(_load(env.jobs_dir / "applications.json")) == ["jobindex.h2"]
    assert not (env.jobs_dir / "output" / OLD_DS).exists()
    out = env.jobs_dir / "output" / "jobindex.h2"
    assert _load(out / "posting.json")["id"] == "jobindex.h2"
    assert (out / "cv.pdf").exists() and (out / "sent" / "cv.tex").read_text() == "sent cv"
    assert result["split"] == 1 and result["applications"] == 1 and result["outputs"] == 1


def test_without_an_output_copy_the_earliest_posting_wins(env):
    import shutil

    shutil.rmtree(env.jobs_dir / "output")
    _migrate(env)
    assert list(_load(env.jobs_dir / "applications.json")) == ["jobindex.h1"]


def test_duplicate_of_follows_the_same_rule(env):
    _migrate(env)
    h3 = _load(env.jobs_dir / "postings" / "2026-10-02" / "jobindex" / "jobindex.h3.json")
    assert h3["duplicate_of"] == "jobindex.h2"


def test_last_list_is_deleted(env):
    _migrate(env)
    assert not (env.jobs_dir / "last_list.json").exists()


def test_a_second_run_changes_nothing(env):
    _migrate(env)
    before = _tree_hash(env.jobs_dir)
    result = _migrate(env)
    assert _tree_hash(env.jobs_dir) == before
    assert result["renamed"] == result["history"] == result["applications"] == result["outputs"] == result["split"] == 0


def test_dry_run_writes_nothing_and_makes_no_backup(env):
    before = _tree_hash(env.jobs_dir)
    result = _migrate(env, dry_run=True)
    assert _tree_hash(env.jobs_dir) == before
    assert not env.backups_dir.exists()
    assert result["dry_run"] is True and result["renamed"] == 4 and result["split"] == 1
    assert result["backup_dir"] is None


def test_a_real_run_backs_up_the_originals_first(env):
    before = _tree_hash(env.jobs_dir)
    result = _migrate(env)
    backup = Path(result["backup_dir"])
    assert backup.parent == env.backups_dir
    assert _tree_hash(backup / "jobs") == before


def test_a_partially_migrated_tree_is_finished(env):
    _migrate(env)
    # an old-format posting appears after a run on another computer
    _write(env.jobs_dir / "postings" / "2026-10-03" / "jobindex" / "jobindex.zed.ds.json",
           _posting("jobindex.zed.ds", "jobindex", "h7", day="2026-10-03", company="Zed"))
    result = _migrate(env)
    assert (env.jobs_dir / "postings" / "2026-10-03" / "jobindex" / "jobindex.h7.json").exists()
    assert result["renamed"] == 1


def test_the_ledger_lock_is_held(env, monkeypatch):
    seen = {}
    real = archive_cmd._new_backup_dir

    def spy(backups_dir):
        seen["holder"] = lock.lock_holder(env.jobs_dir)
        return real(backups_dir)

    monkeypatch.setattr(archive_cmd, "_new_backup_dir", spy)
    _migrate(env)
    assert seen["holder"]["purpose"] == "migrate"


def test_a_job_still_resolves_by_name_after_migration(env):
    _migrate(env)
    found = selection.find_posting(env.jobs_dir, "jobindex.h1")
    assert found["company"] == "Acme"
    assert selection.resolve_job_ref("engineer", env.jobs_dir) == "teamtailor.acme-teamtailor-com-555"


def test_main_dry_run_runs_on_the_workspace_jobs_dir(env, capsys):
    assert script.main(["--dry-run"]) == 0
    assert "Would change" in capsys.readouterr().out
    assert (env.jobs_dir / "postings" / "2026-10-01" / "jobindex" / f"{OLD_DS}.json").exists()
    assert not env.backups_dir.exists()


def test_main_applies(env, capsys):
    assert script.main([]) == 0
    assert "Migrated" in capsys.readouterr().out
    assert (env.jobs_dir / "postings" / "2026-10-01" / "jobindex" / "jobindex.h1.json").exists()
