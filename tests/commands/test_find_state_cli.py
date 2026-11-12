"""CLI/core/MCP tests for run state (issue #145): the ledger lock taken by
`find` and the ledger-writing cores; "since last review" in `status_summary`;
`list --new`; the `reviewed` command.
"""

import json
import subprocess
import sys
import textwrap
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from door.cli import cli
from door.commands import matches as matches_cmd
from door.commands import find as find_cmd
from door.commands import status as status_cmd
from door.commands import match as match_cmd
from door.commands import prepare as prepare_cmd
from door.commands import scrape as scrape_cmd
from door.core import workspace
import door.mcp_server as server
from profile_utils import write_config
from paths import SRC_DIR
from cli_utils import result_text, stub_match_result, stub_steps


def _stub_scrape_and_match(cli_env, monkeypatch):
    """`find` without the network or `claude`: the steps before `match` return canned blocks, and `match`
    runs for real over the postings on disk with scoring and the passes faked."""
    stub_steps(monkeypatch, cli_env.jobs_dir, real=("match",))
    monkeypatch.setattr(scrape_cmd, "_scrape_passes", lambda *a, **k: {})
    monkeypatch.setattr(match_cmd, "_match_core", lambda *a, **k: stub_match_result(cli_env.jobs_dir))


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    write_config(profile_dir, {"role_targets": ["data scientist"], "location": "Copenhagen"})
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)
    return types.SimpleNamespace(profile_dir=profile_dir, jobs_dir=jobs_dir, tmp_path=tmp_path)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


NOW = datetime.now(timezone.utc)


def _write_posting(jobs_dir: Path, job_id: str, *, score=0.9, scraped_at=None, site="jobindex", **extra) -> Path:
    scraped = scraped_at or NOW
    site_dir = jobs_dir / scraped.strftime("%Y-%m-%d") / site
    site_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "id": job_id,
        "title": f"Title {job_id}",
        "company": "Acme",
        "location": "Copenhagen",
        "url": f"https://example.com/{job_id}",
        "description": "d",
        "source": site,
        "scraped_at": _iso(scraped),
        "score": score,
        **extra,
    }
    path = site_dir / f"{job_id}.json"
    path.write_text(json.dumps(data))
    return path


def _write_run(jobs_dir: Path, started: datetime, *, failures=(), new=(), sites=None) -> Path:
    runs_dir = jobs_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "started_at": _iso(started),
        "finished_at": _iso(started + timedelta(minutes=4)),
        "elapsed_s": 240.0,
        "search": {"sites": sites or [{"site": "jobindex", "outcome": "ok", "count": 3}]},
        "match": {"scored": 3, "failed": []},
        "new_above_threshold": list(new),
        "top": [],
        "prepared": None,
        "prepare_error": None,
        "failures": list(failures),
    }
    path = runs_dir / find_cmd._run_record_filename(record["started_at"])
    path.write_text(json.dumps(record))
    return path


def _spawn_holder(jobs_dir: Path, purpose: str = "run") -> subprocess.Popen:
    code = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(SRC_DIR)!r})
        from pathlib import Path
        from door.core.lock import ledger_lock
        with ledger_lock(Path({str(jobs_dir)!r}), {purpose!r}):
            print("held", flush=True)
            sys.stdin.read()
        """
    )
    proc = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    return proc


@pytest.fixture
def run_in_progress(cli_env):
    proc = _spawn_holder(cli_env.jobs_dir, "run")
    yield proc
    proc.stdin.close()
    proc.wait(timeout=10)


# --------------------------------------------------------------------------- #
# ledger lock
# --------------------------------------------------------------------------- #

def test_run_core_holds_the_lock_for_the_whole_run(cli_env, monkeypatch):
    from door.core.lock import lock_holder

    seen = {}
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    steps.on_call = lambda name: seen.update({name: lock_holder(cli_env.jobs_dir)})
    find_cmd._find_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)

    assert set(seen) == {"search", "discover", "follow", "collect", "match"}
    assert all(holder["purpose"] == "run" for holder in seen.values())
    assert lock_holder(cli_env.jobs_dir) is None


def test_run_core_refuses_to_start_while_another_run_holds_the_lock(cli_env, monkeypatch, run_in_progress):
    from door.core.lock import LockHeldError

    stub_steps(monkeypatch, cli_env.jobs_dir).on_call = lambda name: pytest.fail("ran under a held lock")
    with pytest.raises(LockHeldError, match="a run is in progress"):
        find_cmd._find_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)


def test_run_command_exits_1_with_a_clear_message_when_locked(cli_env, run_in_progress):
    result = CliRunner().invoke(cli, ["find"])
    assert result.exit_code == 1
    assert "a run is in progress" in result_text(result)


def test_set_status_is_refused_while_a_run_holds_the_lock(cli_env, run_in_progress):
    from door.core.lock import LockHeldError

    with pytest.raises(LockHeldError):
        status_cmd._set_status_core("jobindex-acme-ds", "applied", jobs_dir=cli_env.jobs_dir)
    assert not (cli_env.jobs_dir / "applications.json").exists()


def test_status_command_reports_the_lock(cli_env, run_in_progress):
    result = CliRunner().invoke(cli, ["jobs", "status", "jobindex-acme-ds", "applied"])
    assert result.exit_code == 1
    assert f"pid {run_in_progress.pid}" in result_text(result)


def test_set_status_tool_returns_an_error_dict_while_locked(cli_env, run_in_progress):
    result = server.set_status("jobindex-acme-ds", "applied")
    assert "a run is in progress" in result["error"]


def test_scrape_core_takes_the_lock(cli_env, monkeypatch, run_in_progress):
    from door.core.lock import LockHeldError

    with pytest.raises(LockHeldError):
        scrape_cmd._scrape_core(["jobindex"], jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)


# --------------------------------------------------------------------------- #
# reviewed / since_last_review / list --new
# --------------------------------------------------------------------------- #

def test_mark_reviewed_core_stamps_last_review(cli_env):
    result = status_cmd._mark_reviewed_core(jobs_dir=cli_env.jobs_dir)
    stamp = json.loads((cli_env.jobs_dir / "last_review.json").read_text())
    assert stamp["reviewed_at"] == result["reviewed_at"]
    assert datetime.fromisoformat(stamp["reviewed_at"]) <= datetime.now(timezone.utc)
    assert result["previous"] is None

    again = status_cmd._mark_reviewed_core(jobs_dir=cli_env.jobs_dir)
    assert again["previous"] == result["reviewed_at"]


def test_mark_reviewed_tool_stamps_the_watermark(cli_env):
    assert "reviewed_at" in server.mark_reviewed()
    assert (cli_env.jobs_dir / "last_review.json").exists()


def test_since_last_review_counts_runs_new_matches_and_site_failures(cli_env):
    reviewed = NOW - timedelta(days=1)
    (cli_env.jobs_dir / "last_review.json").write_text(json.dumps({"reviewed_at": _iso(reviewed)}))

    _write_run(cli_env.jobs_dir, reviewed - timedelta(hours=5))  # before the review: ignored
    _write_run(
        cli_env.jobs_dir,
        reviewed + timedelta(hours=5),
        failures=["linkedin"],
        sites=[
            {"site": "jobindex", "outcome": "ok", "count": 2},
            {"site": "linkedin", "outcome": "failed", "count": 0, "errors": ["HTTP 999"]},
        ],
    )
    _write_run(cli_env.jobs_dir, reviewed + timedelta(hours=10))

    _write_posting(cli_env.jobs_dir, "old-match", scraped_at=reviewed - timedelta(hours=3))
    _write_posting(cli_env.jobs_dir, "new-match", scraped_at=reviewed + timedelta(hours=5))
    _write_posting(cli_env.jobs_dir, "new-weak", score=0.1, scraped_at=reviewed + timedelta(hours=5))

    summary = status_cmd._status_summary_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)
    since = summary["since_last_review"]

    assert since["last_reviewed_at"] == _iso(reviewed)
    assert since["runs"] == 2
    assert since["new_matches"] == 1
    assert since["site_failures"] == [{"site": "linkedin", "outcome": "failed", "errors": ["HTTP 999"]}]
    assert since["last_run"]["started_at"] == _iso(reviewed + timedelta(hours=10))
    assert since["last_run"]["outcome"] == "ok"


def test_since_last_review_without_a_review_counts_everything(cli_env):
    _write_run(cli_env.jobs_dir, NOW - timedelta(days=2))
    _write_posting(cli_env.jobs_dir, "a-match")
    since = status_cmd._status_summary_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["since_last_review"]
    assert since["last_reviewed_at"] is None
    assert since["runs"] == 1
    assert since["new_matches"] == 1
    assert since["site_failures"] == []


def test_status_summary_without_any_runs(cli_env):
    since = status_cmd._status_summary_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["since_last_review"]
    assert since == {"last_reviewed_at": None, "runs": 0, "last_run": None, "new_matches": 0, "site_failures": []}


def test_status_command_prints_since_last_review(cli_env):
    reviewed = NOW - timedelta(days=1)
    (cli_env.jobs_dir / "last_review.json").write_text(json.dumps({"reviewed_at": _iso(reviewed)}))
    _write_run(cli_env.jobs_dir, reviewed + timedelta(hours=1))
    _write_posting(cli_env.jobs_dir, "new-match", scraped_at=reviewed + timedelta(hours=1))
    result = CliRunner().invoke(cli, ["jobs", "summary"])
    assert result.exit_code == 0, result_text(result)
    assert "Since last review" in result.output
    assert "1 new match" in result.output


def test_list_new_only_filters_on_first_seen_after_the_review(cli_env):
    reviewed = NOW - timedelta(days=1)
    (cli_env.jobs_dir / "last_review.json").write_text(json.dumps({"reviewed_at": _iso(reviewed)}))
    _write_posting(cli_env.jobs_dir, "old-match", score=0.95, scraped_at=reviewed - timedelta(hours=3))
    _write_posting(cli_env.jobs_dir, "new-match", score=0.8, scraped_at=reviewed + timedelta(hours=3))

    rows = matches_cmd._list_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["matches"]
    assert [(r["id"], r["is_new"]) for r in rows] == [("old-match", False), ("new-match", True)]

    rows = matches_cmd._list_core(new_only=True, jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["matches"]
    assert [r["id"] for r in rows] == ["new-match"]
    assert "rank" not in rows[0]

    result = CliRunner().invoke(cli, ["jobs", "list", "--new"])
    assert "new-match" in result.output and "old-match" not in result.output

    assert [r["id"] for r in server.list_matches(new_only=True)["matches"]] == ["new-match"]


def test_list_everything_is_new_before_the_first_review(cli_env):
    _write_posting(cli_env.jobs_dir, "a-match")
    rows = matches_cmd._list_core(new_only=True, jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["matches"]
    assert [(r["id"], r["is_new"]) for r in rows] == [("a-match", True)]


def test_mark_seen_takes_one_match_out_of_the_new_ones(cli_env):
    reviewed = NOW - timedelta(days=1)
    (cli_env.jobs_dir / "last_review.json").write_text(json.dumps({"reviewed_at": _iso(reviewed)}))
    _write_posting(cli_env.jobs_dir, "seen-match", score=0.9, scraped_at=reviewed + timedelta(hours=3))
    _write_posting(cli_env.jobs_dir, "unseen-match", score=0.8, scraped_at=reviewed + timedelta(hours=3))

    result = status_cmd._mark_seen_core("seen-match", jobs_dir=cli_env.jobs_dir)
    assert result == {"job_id": "seen-match"}

    rows = matches_cmd._list_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["matches"]
    assert [(r["id"], r["is_new"]) for r in rows] == [("seen-match", False), ("unseen-match", True)]
    rows = matches_cmd._list_core(new_only=True, jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["matches"]
    assert [r["id"] for r in rows] == ["unseen-match"]
    since = status_cmd._status_summary_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["since_last_review"]
    assert since["new_matches"] == 1
    # the review's own stamp stays: runs and site failures still count from it
    assert since["last_reviewed_at"] == _iso(reviewed)


def test_mark_seen_works_before_the_first_review(cli_env):
    _write_posting(cli_env.jobs_dir, "a-match")
    status_cmd._mark_seen_core("a-match", jobs_dir=cli_env.jobs_dir)
    rows = matches_cmd._list_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["matches"]
    assert [(r["id"], r["is_new"]) for r in rows] == [("a-match", False)]
    since = status_cmd._status_summary_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["since_last_review"]
    assert since["last_reviewed_at"] is None


def test_mark_seen_twice_keeps_one_entry(cli_env):
    _write_posting(cli_env.jobs_dir, "a-match")
    status_cmd._mark_seen_core("a-match", jobs_dir=cli_env.jobs_dir)
    status_cmd._mark_seen_core("a-match", jobs_dir=cli_env.jobs_dir)
    assert json.loads((cli_env.jobs_dir / "last_review.json").read_text())["seen"] == ["a-match"]


def test_mark_reviewed_covers_what_was_seen_one_by_one(cli_env):
    _write_posting(cli_env.jobs_dir, "a-match", scraped_at=NOW - timedelta(hours=1))
    status_cmd._mark_seen_core("a-match", jobs_dir=cli_env.jobs_dir)
    status_cmd._mark_reviewed_core(jobs_dir=cli_env.jobs_dir)
    assert "seen" not in json.loads((cli_env.jobs_dir / "last_review.json").read_text())
    rows = matches_cmd._list_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["matches"]
    assert [(r["id"], r["is_new"]) for r in rows] == [("a-match", False)]


def test_mark_seen_tool_marks_the_job(cli_env):
    _write_posting(cli_env.jobs_dir, "jobindex-acme-ds")
    assert server.mark_seen("jobindex-acme-ds") == {"job_id": "jobindex-acme-ds"}
    assert server.list_matches(new_only=True)["matches"] == []


def test_mark_seen_is_refused_while_locked(cli_env, run_in_progress):
    from door.core.lock import LockHeldError

    with pytest.raises(LockHeldError):
        status_cmd._mark_seen_core("jobindex-acme-ds", jobs_dir=cli_env.jobs_dir)


def test_mark_reviewed_is_refused_while_locked(cli_env, run_in_progress):
    from door.core.lock import LockHeldError

    with pytest.raises(LockHeldError):
        status_cmd._mark_reviewed_core(jobs_dir=cli_env.jobs_dir)


# --------------------------------------------------------------------------- #
# review fixes
# --------------------------------------------------------------------------- #

def test_prepare_refuses_before_tailoring_while_a_run_holds_the_lock(cli_env, monkeypatch, run_in_progress):
    _write_posting(cli_env.jobs_dir, "jobindex-acme-ds")
    monkeypatch.setattr(prepare_cmd, "_run_tailor", lambda *a, **k: pytest.fail("tailored under a held lock"))
    result = prepare_cmd._prepare_core("jobindex-acme-ds", jobs_dir=cli_env.jobs_dir)
    assert result["outcome"] == "failed"
    assert "a run is in progress" in result["error"]


def test_since_last_review_and_find_ignore_stale_postings(cli_env, monkeypatch):
    _write_posting(cli_env.jobs_dir, "old-ad", score=0.99, posted_at=_iso(NOW - timedelta(days=60)))
    _write_posting(cli_env.jobs_dir, "fresh-ad", score=0.7)
    since = status_cmd._status_summary_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["since_last_review"]
    assert since["new_matches"] == 1

    # the run scores both (only what a run scores can be one of its new matches)
    def posting_file(job_id):
        return next(cli_env.jobs_dir.rglob(f"{job_id}.json"))  # status moved the day's folder under postings/

    scores = {}
    for job_id in ("old-ad", "fresh-ad"):
        data = json.loads(posting_file(job_id).read_text())
        scores[job_id] = data.pop("score")
        posting_file(job_id).write_text(json.dumps(data))

    def score(*a, **k):
        for job_id, value in scores.items():
            path = posting_file(job_id)
            path.write_text(json.dumps({**json.loads(path.read_text()), "score": value}))
        return stub_match_result(cli_env.jobs_dir)

    _stub_scrape_and_match(cli_env, monkeypatch)
    monkeypatch.setattr(match_cmd, "_match_core", score)
    record = find_cmd._find_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)
    assert record["new_above_threshold"] == ["fresh-ad"]


def test_since_last_review_flags_sites_that_returned_nothing(cli_env):
    _write_run(
        cli_env.jobs_dir,
        NOW - timedelta(hours=1),
        sites=[{"site": "jobindex", "outcome": "empty", "count": 0, "errors": [], "warning": "returned no results at all"}],
    )
    since = status_cmd._status_summary_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["since_last_review"]
    assert since["site_failures"] == [{"site": "jobindex", "outcome": "empty", "errors": ["returned no results at all"]}]


def test_since_last_review_reads_the_search_and_collect_blocks_of_a_run(cli_env):
    path = _write_run(cli_env.jobs_dir, NOW - timedelta(hours=1), failures=["lever"])
    record = json.loads(path.read_text())
    record.pop("search")
    record["search"] = {"sites": [{"site": "jobindex", "outcome": "ok", "count": 3}]}
    record["collect"] = {"sites": [{"site": "lever", "outcome": "failed", "count": 0, "errors": ["HTTP 500"]},
                                   {"site": "greenhouse", "outcome": "ok", "count": 4}]}
    path.write_text(json.dumps(record))

    since = status_cmd._status_summary_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["since_last_review"]

    assert since["site_failures"] == [{"site": "lever", "outcome": "failed", "errors": ["HTTP 500"]}]
    assert since["last_run"]["scraped"] == 7 and since["last_run"]["failures"] == ["lever"]


def test_status_summary_reports_in_progress_for_lock_held_by_other_process(cli_env):
    from door.commands import status as status_cmd
    from door.core.progress import Progress, ProgressFile

    proc = _spawn_holder(cli_env.jobs_dir, "run")
    try:
        ProgressFile(cli_env.jobs_dir / ".progress.json").report(Progress("match", 1, 2, stage="run"))
        live = status_cmd._status_summary_core(cli_env.jobs_dir, cli_env.profile_dir)["in_progress"]
        assert live["pid"] == proc.pid
        assert live["message"] == "match"
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)

    assert status_cmd._status_summary_core(cli_env.jobs_dir, cli_env.profile_dir)["in_progress"] is None


def test_status_command_marks_the_last_run_and_failed_sites(cli_env):
    reviewed = NOW - timedelta(days=1)
    (cli_env.jobs_dir / "last_review.json").write_text(json.dumps({"reviewed_at": _iso(reviewed)}))
    _write_run(
        cli_env.jobs_dir, reviewed + timedelta(hours=1), failures=["linkedin"],
        sites=[{"site": "linkedin", "outcome": "failed", "count": 0, "errors": ["HTTP 999"]}],
    )

    text = result_text(CliRunner().invoke(cli, ["jobs", "summary"]))

    assert "✗ failed (linkedin)" in text
    assert "✗ linkedin" in text and "HTTP 999" in text


def test_status_command_marks_an_ok_last_run(cli_env):
    _write_run(cli_env.jobs_dir, NOW - timedelta(hours=2))

    assert "✓ ok" in result_text(CliRunner().invoke(cli, ["jobs", "summary"]))


def test_list_rows_carry_work_permit(cli_env):
    _write_posting(cli_env.jobs_dir, "flagged", score=0.9, work_permit="no_sponsorship")
    _write_posting(cli_env.jobs_dir, "plain", score=0.8)

    rows = matches_cmd._list_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["matches"]
    assert {r["id"]: r["work_permit"] for r in rows} == {"flagged": "no_sponsorship", "plain": None}
