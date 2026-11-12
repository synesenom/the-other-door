"""`data report` / `report_problem` (#593): one archive to send when something went wrong.

It holds the logs, the last run records (counts, outcomes and errors only), doctor's checks and
the versions; emails and home folders are masked; nothing from profile/, no postings, no ledger.
"""

import json
import types
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

import door.mcp_server as server
from door import version as version_mod
from door.cli import cli
from door.commands import report as report_cmd
from door.commands import setup as setup_cmd
from door.core import workspace
from cli_utils import result_text
from profile_utils import write_config

_CV = "# Ada Lovelace\nAnalytical engines, secret CV line"
_AD = "We are hiring a Head of Secret Plans"


def _record(n: int) -> dict:
    return {
        "started_at": f"2026-10-2{n}T09:00:00+00:00", "finished_at": f"2026-10-2{n}T09:05:00+00:00", "elapsed_s": 300.0,
        "steps": ["search", "match"], "skipped": {"discover": "--skip"},
        "search": {"summary": "12 postings from 2 boards", "elapsed_s": 40.0, "postings": 12, "sites": [
            {"site": "jobindex", "outcome": "ok", "count": 12, "dir": "/somewhere/jobs/postings/x"},
            {"site": "thehub", "outcome": "failed", "count": 0, "errors": ["HTTP 503"]},
        ]},
        "discover": None, "follow": None, "collect": None,
        "match": {"summary": "11 scored", "scored": 11, "failed": ["jobindex.9"],
                  "failures": [{"id": "jobindex.9", "error": "claude timed out"}], "above_threshold": 2,
                  "candidates_dir": "/somewhere/jobs/postings/2026-10-26"},
        "new_above_threshold": ["jobindex.1"],
        "top": [{"id": "jobindex.1", "score": 0.9, "title": "Head of Secret Plans", "company": "Acme"}],
        "failures": ["thehub", "jobindex.9"],
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    profile_dir, jobs_dir = home / "profile", home / "jobs"
    write_config(profile_dir, {"role_targets": ["data scientist"], "location": "Copenhagen"})
    (profile_dir / "cv.md").write_text(_CV)
    posting = jobs_dir / "postings" / "2026-10-26" / "jobindex" / "jobindex.1.json"
    posting.parent.mkdir(parents=True)
    posting.write_text(json.dumps({"id": "jobindex.1", "description": _AD}))
    (jobs_dir / "applications.json").write_text('{"jobindex.1": {"status": "applied", "notes": "Head of Secret Plans"}}')
    runs = jobs_dir / "runs"
    runs.mkdir()
    for n in range(8):
        (runs / f"2026-10-2{n}T09-00-00-00-00.json").write_text(json.dumps(_record(n)))
    (runs / "latest.log").write_text("2026-10-27T09:00 ok\n")
    logs = home / "logs"
    logs.mkdir()
    (logs / "door.log").write_text(
        f"2026-10-26T09:00:00Z ERROR tool export_data: {home}/out.tar.gz already exists\n"
        "2026-10-26T09:01:00Z ERROR tool connect_drive: signed in as ada.lovelace@example.com, then refused\n"
        f"2026-10-26T09:02:00Z ERROR app server stopped: File \"{tmp_path / 'user'}/x.py\"\n")
    (logs / "door.log.1").write_text("2026-10-25T09:00:00Z WARNING tool market: older\n")
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setattr(workspace, "HOME", home)
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(setup_cmd, "_doctor_core", lambda *a, **k: {
        "ok": False,
        "checks": [
            {"name": "profile", "status": "ok", "required": True, "detail": f"{profile_dir}/config.json is valid", "fix": None},
            {"name": "claude login", "status": "ok", "required": True, "detail": "logged in (ada.lovelace@example.com, max)",
             "fix": None, "details": {"config_dir": str(user / ".claude")}},
            {"name": "latex", "status": "missing", "required": True, "detail": "no tectonic", "fix": "./door doctor --fix"},
        ],
        "last_run": {"started_at": "2026-10-27T09:00:00+00:00", "outcome": "failed", "failures": ["thehub"]},
        "last_scrape": [],
    })
    out = tmp_path / "out"
    out.mkdir()
    return types.SimpleNamespace(home=home, profile_dir=profile_dir, jobs_dir=jobs_dir, user=user, out=out, tmp_path=tmp_path)


def _report(env, path=None):
    return report_cmd._report_core(path if path is not None else env.out)


def _contents(path) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        return {name: z.read(name).decode("utf-8") for name in z.namelist()}


def test_writes_one_zip_with_the_logs_runs_checks_and_versions(env):
    result = _report(env)
    path = Path(result["path"])
    assert path.parent == env.out and path.name.startswith("door-report-") and path.suffix == ".zip"
    assert result["bytes"] == path.stat().st_size
    files = _contents(path)
    assert set(files) == {
        "README.txt", "about.json", "doctor.json", "logs/door.log", "logs/door.log.1",
        *(f"runs/2026-10-2{n}T09-00-00-00-00.json" for n in range(3, 8)),
    }
    assert sorted(result["files"]) == sorted(files)
    about = json.loads(files["about.json"])
    assert about["version"] == version_mod.VERSION
    assert about["os"] and about["python"]
    checks = json.loads(files["doctor.json"])["checks"]
    assert [c["name"] for c in checks] == ["profile", "claude login", "latex"]
    assert "older" in files["logs/door.log.1"]


def test_a_run_record_keeps_counts_outcomes_and_errors_only(env):
    run = json.loads(_contents(_report(env)["path"])["runs/2026-10-27T09-00-00-00-00.json"])
    assert run["started_at"] == "2026-10-27T09:00:00+00:00"
    assert run["failures"] == ["thehub", "jobindex.9"]
    assert run["search"]["summary"] == "12 postings from 2 boards"
    assert run["search"]["postings"] == 12
    assert run["search"]["sites"][1] == {"site": "thehub", "outcome": "failed", "count": 0, "errors": ["HTTP 503"]}
    assert "dir" not in run["search"]["sites"][0]
    assert run["match"]["failures"] == [{"id": "jobindex.9", "error": "claude timed out"}]
    assert "candidates_dir" not in run["match"]
    assert "top" not in run and run["discover"] is None


def test_emails_and_home_folders_are_masked_everywhere(env):
    text = "\n".join(_contents(_report(env)["path"]).values())
    assert "ada.lovelace@example.com" not in text and "<email>" in text
    assert str(env.home) not in text and str(env.user) not in text
    assert "<data folder>/out.tar.gz" in text
    assert "~/x.py" in text


def test_nothing_from_the_profile_postings_or_ledger(env):
    files = _contents(_report(env)["path"])
    assert not any(name.startswith(("profile/", "jobs/")) for name in files)
    text = "\n".join(files.values())
    assert "secret CV line" not in text and "Secret Plans" not in text and "Copenhagen" not in text


def test_never_replaces_a_file(env):
    target = env.out / "mine.zip"
    target.write_text("keep me")
    with pytest.raises(FileExistsError):
        _report(env, target)
    assert target.read_text() == "keep me"


def test_a_name_without_zip_gets_it(env):
    assert _report(env, env.out / "for-ada")["path"] == str(env.out / "for-ada.zip")


def test_a_failing_doctor_still_gives_a_report(env, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("doctor fell over")

    monkeypatch.setattr(setup_cmd, "_doctor_core", broken)
    files = _contents(_report(env)["path"])
    assert "doctor fell over" in json.loads(files["doctor.json"])["error"]


def test_an_empty_data_folder_still_gives_a_report(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(workspace, "HOME", home)
    monkeypatch.setattr(workspace, "PROFILE_DIR", home / "profile")
    monkeypatch.setattr(workspace, "JOBS_DIR", home / "jobs")
    monkeypatch.setattr(setup_cmd, "_doctor_core", lambda *a, **k: {"ok": False, "checks": []})
    files = _contents(report_cmd._report_core(tmp_path)["path"])
    assert set(files) == {"README.txt", "about.json", "doctor.json"}


def test_the_command_says_where_it_wrote(env, monkeypatch):
    monkeypatch.chdir(env.tmp_path)
    result = CliRunner().invoke(cli, ["data", "report", str(env.out / "r.zip")])
    assert result.exit_code == 0, result_text(result)
    assert "r.zip" in result_text(result)
    assert (env.out / "r.zip").is_file()


def test_the_command_refuses_an_existing_file(env):
    (env.out / "r.zip").write_text("x")
    result = CliRunner().invoke(cli, ["data", "report", str(env.out / "r.zip")])
    assert result.exit_code == 1
    assert "already exists" in result_text(result)


def test_the_tool_calls_the_core(env, monkeypatch):
    monkeypatch.setenv("DOOR_PATHS_FROM_DIALOGS", "1")  # the desktop app's paths come from its save dialog
    result = server.report_problem(str(env.out / "t.zip"))
    assert result["path"] == str(env.out / "t.zip")
    assert "error" in server.report_problem(str(env.out / "t.zip"))
    assert "report_problem" in server.WRITING_TOOLS
    assert server.CLI_COMMAND_TOOLS["data report"] == ("report_problem",)


def test_the_data_folder_is_masked_as_door_home_spells_it_too(env, monkeypatch):
    link = env.tmp_path / "link-to-home"
    link.symlink_to(env.home)
    monkeypatch.setenv("DOOR_HOME", str(link))
    (env.home / "logs" / "door.log").write_text(f"2026-10-26T09:00:00Z ERROR tool show: {link}/jobs/x.json is broken\n")
    text = _contents(_report(env)["path"])["logs/door.log"]
    assert str(link) not in text and "<data folder>/jobs/x.json" in text


def test_saving_a_report_stamps_when_so_what_came_before_is_said_no_more(env):
    from door.core import recurring

    assert recurring.reported_at(env.home) is None
    _report(env)
    assert recurring.reported_at(env.home) is not None
    assert "logs/reported_at" not in _contents(next(env.out.glob("*.zip")))


def test_a_report_that_could_not_be_written_stamps_nothing(env):
    from door.core import recurring

    (env.out / "taken.zip").write_text("x")
    with pytest.raises(FileExistsError):
        _report(env, env.out / "taken.zip")
    assert recurring.reported_at(env.home) is None
