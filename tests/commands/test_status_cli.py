"""`status`: set an application's status, and the zero-argument pipeline dashboard.

Split out of the former tests/test_door_cli.py (issue #15 onward); the shared
`cli_env` fixture is in tests/commands/conftest.py, helpers in tests/cli_utils.py.
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from door.cli import cli
from cli_utils import FRESH_SCRAPED_AT, result_text


# --------------------------------------------------------------------------- #
# status (issue #26)
# --------------------------------------------------------------------------- #

def test_status_command_sets_status(cli_env, monkeypatch):
    """status <job_id> <status> calls set_status and save on the tracker."""
    import door.core.tracker as tracker_mod

    calls = {}

    class FakeTracker:
        def __init__(self, path):
            calls["path"] = path

        def set_status(self, job_id, status, **kwargs):
            calls["set_status"] = (job_id, status)

        def save(self):
            calls["save"] = True

        def history(self, job_id):
            return [{}]

        def get_status(self, job_id):
            return calls["set_status"][1]

    monkeypatch.setattr(tracker_mod, "ApplicationTracker", FakeTracker)

    result = CliRunner().invoke(cli, ["jobs", "status", "job-abc", "applied"])
    assert result.exit_code == 0, result_text(result)
    assert calls.get("set_status") == ("job-abc", "applied")
    assert calls.get("save") is True
    assert calls["path"] == cli_env.jobs_dir / "applications.json"
    # Confirmation message shown, with no None leaking from the optional args
    assert "job-abc" in result_text(result)
    assert "None" not in result_text(result)


def test_status_invalid_status_shows_error(cli_env, monkeypatch):
    """When set_status raises ValueError, exit code is 1 and error is printed."""
    import door.core.tracker as tracker_mod

    class FakeTracker:
        def __init__(self, path):
            pass

        def set_status(self, job_id, status, **kwargs):
            raise ValueError("unknown status 'hired'")

        def save(self):
            pass  # pragma: no cover — should not be reached

    monkeypatch.setattr(tracker_mod, "ApplicationTracker", FakeTracker)

    result = CliRunner().invoke(cli, ["jobs", "status", "job-abc", "hired"])
    assert result.exit_code != 0
    assert "hired" in result_text(result)


def test_status_duplicate_application_shows_error(cli_env, monkeypatch):
    """When set_status raises DuplicateApplicationError, exit code is 1."""
    import door.core.tracker as tracker_mod
    from door.core.tracker import DuplicateApplicationError

    class FakeTracker:
        def __init__(self, path):
            pass

        def set_status(self, job_id, status, **kwargs):
            raise DuplicateApplicationError("already applied")

        def save(self):
            pass  # pragma: no cover — should not be reached

        def history(self, job_id):
            return [{"status": "applied"}]

    monkeypatch.setattr(tracker_mod, "ApplicationTracker", FakeTracker)

    result = CliRunner().invoke(cli, ["jobs", "status", "job-abc", "applied"])
    assert result.exit_code == 1
    assert "already applied" in result_text(result) or "duplicate" in result_text(result).lower()


# --------------------------------------------------------------------------- #
# status — zero-arg pipeline dashboard (issue #71)
# --------------------------------------------------------------------------- #

def _write_status_posting(jobs_dir: Path, date: str, site: str, job_id: str, **overrides) -> Path:
    site_dir = jobs_dir / "postings" / date / site
    site_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "id": job_id,
        "title": "Data Scientist",
        "company": "Acme",
        "location": "Copenhagen",
        "url": "https://example.com/job/1",
        "description": "d",
        "source": site,
        "scraped_at": FRESH_SCRAPED_AT,
    }
    data.update(overrides)
    path = site_dir / f"{job_id}.json"
    path.write_text(json.dumps(data))
    return path


def test_status_no_args_prints_pipeline_summary(cli_env):
    _write_status_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-excluded", score=0.0, score_reason="excluded")
    _write_status_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-high", score=0.9)
    _write_status_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-low", score=0.1)

    cli_env.jobs_dir.mkdir(parents=True, exist_ok=True)
    (cli_env.jobs_dir / "applications.json").write_text(json.dumps({
        "job-a": {"status": "applied", "updated_at": "2026-07-01T00:00:00Z"},
        "job-b": {"status": "unapplied", "updated_at": "2026-07-02T00:00:00Z"},
    }))

    result = CliRunner().invoke(cli, ["jobs", "summary"])
    text = result_text(result)
    assert result.exit_code == 0, text

    assert "3" in text  # total postings
    assert "1" in text  # excluded, above_threshold, unapplied all happen to be 1
    for label in ("unapplied", "prepared", "applied", "interview:screening", "ghosted", "rejected", "offer", "discarded"):
        assert label in text


def test_status_with_only_a_job_picks_the_status_from_one_list(cli_env, prompts):
    from door.core.tracker import ApplicationTracker

    prompts.answers = {"status": "interview:assessment", "notes": "numerical test"}

    result = CliRunner().invoke(cli, ["jobs", "status", "job-abc"])

    assert result.exit_code == 0, result_text(result)
    assert [value for _, value in prompts.asked["status"]["choices"]] == [
        "unapplied", "prepared", "applied",
        "interview:screening", "interview:impression", "interview:assessment", "interview:technical",
        "ghosted", "rejected", "offer", "discarded",
    ]
    entry = ApplicationTracker(cli_env.jobs_dir / "applications.json").history("job-abc")[-1]
    assert (entry["status"], entry["notes"]) == ("interview:assessment", "numerical test")


def test_status_alone_picks_the_job_from_a_list_in_play_first(cli_env, prompts):
    from door.core.tracker import ApplicationTracker

    _write_status_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-top", score=0.9, title="Top match")
    _write_status_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-wpp", score=0.7, title="Team Lead", company="WPP")
    _write_status_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-gone", score=0.95)
    CliRunner().invoke(cli, ["jobs", "status", "job-wpp", "interview:screening"])
    CliRunner().invoke(cli, ["jobs", "status", "job-gone", "discarded"])
    prompts.answers = {"job": "job-wpp", "status": "interview:technical"}

    result = CliRunner().invoke(cli, ["jobs", "status"])

    assert result.exit_code == 0, result_text(result)
    choices = prompts.asked["job"]["choices"]
    assert [value for _, value in choices] == ["job-wpp", "job-top"]
    assert "Team Lead — WPP  [interview:screening]" == choices[0][0]
    assert ApplicationTracker(cli_env.jobs_dir / "applications.json").get_status("job-wpp") == "interview:technical"


def test_status_alone_with_nothing_to_pick_says_so(cli_env, prompts):
    result = CliRunner().invoke(cli, ["jobs", "status"])

    assert result.exit_code == 0
    assert "No postings to pick from" in result_text(result)


# --------------------------------------------------------------------------- #
# in-progress block (issue #202)
# --------------------------------------------------------------------------- #

def test_status_summary_in_progress_while_lock_held_with_progress_file(cli_env):
    from door.commands import status as status_cmd
    from door.core import progress
    from door.core.lock import ledger_lock

    with ledger_lock(cli_env.jobs_dir, "run"):
        progress.report("scraping (site 2/5)", site="jobindex", stage="scrape")
        result = status_cmd._status_summary_core(cli_env.jobs_dir, cli_env.profile_dir)

    live = result["in_progress"]
    assert live["purpose"] == "run"
    assert live["pid"] > 0 and live["started_at"] and live["updated_at"]
    assert (live["message"], live["site"], live["stage"]) == ("scraping (site 2/5)", "jobindex", "scrape")


def test_status_summary_in_progress_is_none_when_lock_free_even_with_stale_file(cli_env):
    from door.commands import status as status_cmd

    cli_env.jobs_dir.mkdir(parents=True, exist_ok=True)
    (cli_env.jobs_dir / ".progress.json").write_text(json.dumps({"message": "stale"}))
    result = status_cmd._status_summary_core(cli_env.jobs_dir, cli_env.profile_dir)
    assert result["in_progress"] is None


def test_status_summary_in_progress_is_none_when_lock_held_without_progress_file(cli_env):
    from door.commands import status as status_cmd
    from door.core.lock import ledger_lock

    with ledger_lock(cli_env.jobs_dir, "set_status"):
        result = status_cmd._status_summary_core(cli_env.jobs_dir, cli_env.profile_dir)
    assert result["in_progress"] is None


def test_status_command_prints_in_progress_block(cli_env):
    from door.core import progress
    from door.core.lock import ledger_lock

    with ledger_lock(cli_env.jobs_dir, "run"):
        progress.report("scraping (site 2/5)", site="jobindex", stage="scrape")
        busy = CliRunner().invoke(cli, ["jobs", "summary"])
    idle = CliRunner().invoke(cli, ["jobs", "summary"])

    assert busy.exit_code == 0, result_text(busy)
    assert "In progress: run (started " in busy.output
    assert "jobindex: scraping (site 2/5)" in busy.output
    assert busy.output.index("In progress:") < busy.output.index("Postings")
    assert "In progress" not in idle.output


def _line_with(text: str, label: str) -> str:
    """The first line that starts (after indentation) with `label`."""
    return next(line for line in text.splitlines() if line.strip().startswith(label))


def test_status_charts_all_postings_the_applicable_ones_and_those_above_the_threshold(cli_env):
    _write_status_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-excluded", score=0.0, score_reason="excluded")
    _write_status_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-high", score=0.9)
    _write_status_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-low", score=0.1)

    text = result_text(CliRunner().invoke(cli, ["jobs", "summary"]))

    legend = _line_with(text, "█ ≥")
    assert "█ ≥ 0.6" in legend and "1" in legend
    assert "▒ applicable 2" in legend
    assert "░ filtered out 1" in legend
    # One bar over all three postings: a third each above the threshold, applicable below it, filtered out.
    bar = next(line.strip() for line in text.splitlines() if line.strip().startswith(("█", "▒", "░")) and "applicable" not in line)
    assert bar.count("█") == bar.count("▒") == bar.count("░") == 10


def test_status_splits_the_matches_into_unapplied_prepared_and_applied(cli_env):
    for job_id in ("job-a", "job-b", "job-c", "job-d"):
        _write_status_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", job_id, score=0.9)
    (cli_env.jobs_dir / "applications.json").write_text(json.dumps({
        "job-b": {"status": "prepared", "updated_at": "2026-07-01T00:00:00Z"},
        "job-c": {"status": "applied", "updated_at": "2026-07-01T00:00:00Z"},
        "job-d": {"status": "interview", "updated_at": "2026-07-01T00:00:00Z"},
    }))

    text = result_text(CliRunner().invoke(cli, ["jobs", "summary"]))

    assert "4 matches" in text
    legend = _line_with(text, "█ unapplied")
    assert "█ unapplied 1" in legend and "▓ prepared 1" in legend and "▒ applied 2" in legend
    assert "discarded" not in legend  # only shown when there is one


def test_status_lists_the_ledger_counts(cli_env):
    cli_env.jobs_dir.mkdir(parents=True, exist_ok=True)
    (cli_env.jobs_dir / "applications.json").write_text(json.dumps({
        "job-a": {"status": "applied", "updated_at": "2026-07-01T00:00:00Z"},
        "job-b": {"status": "applied", "updated_at": "2026-07-02T00:00:00Z"},
    }))

    text = result_text(CliRunner().invoke(cli, ["jobs", "summary"]))

    assert "Applications" in text
    assert "2" in _line_with(text, "applied")


def test_status_into_a_pipe_has_no_colour_codes(cli_env):
    assert "\x1b[" not in CliRunner().invoke(cli, ["jobs", "summary"]).output


def test_status_on_a_terminal_is_coloured(cli_env, monkeypatch):
    from door.commands import _common as common

    monkeypatch.setattr(common, "_stdout_is_tty", lambda: True)
    assert "\x1b[" in CliRunner().invoke(cli, ["jobs", "summary"]).output


def test_status_with_an_empty_ledger_says_so_in_one_line(cli_env):
    text = result_text(CliRunner().invoke(cli, ["jobs", "summary"]))

    assert "No applications yet" in text
    assert not any(line.strip().startswith("interview") for line in text.splitlines())


# --------------------------------------------------------------------------- #
# the employer list in the summary
# --------------------------------------------------------------------------- #

def _seed_employers(profile_dir):
    from door.core import companies

    items: list = []
    companies.record(items, "Pleo", feed=("ashby", "pleo"), status="followed", found_via="manual")
    companies.record(items, "Danske Bank", feed=None, status="unfollowable", reason="x", found_via="jobindex")
    companies.save(profile_dir, items)


def test_status_summary_counts_the_employers_by_status(cli_env):
    from door.commands import status as status_cmd

    assert status_cmd._status_summary_core(cli_env.jobs_dir, cli_env.profile_dir)["employers"] == {
        "followed": 0, "unfollowable": 0, "unresolved": 0, "dormant": 0}
    _seed_employers(cli_env.profile_dir)
    assert status_cmd._status_summary_core(cli_env.jobs_dir, cli_env.profile_dir)["employers"] == {
        "followed": 1, "unfollowable": 1, "unresolved": 0, "dormant": 0}


def test_status_prints_the_employer_counts_only_when_there_are_employers(cli_env):
    assert "Employers" not in result_text(CliRunner().invoke(cli, ["jobs", "summary"]))
    _seed_employers(cli_env.profile_dir)
    text = result_text(CliRunner().invoke(cli, ["jobs", "summary"]))
    assert "Employers" in text and "1 followed" in text and "1 unfollowable" in text


def test_status_summary_shows_how_each_kind_of_interview_went(cli_env):
    runner = CliRunner()
    runner.invoke(cli, ["jobs", "status", "job-a", "interview:screening"])
    runner.invoke(cli, ["jobs", "status", "job-a", "interview:technical"])
    runner.invoke(cli, ["jobs", "status", "job-a", "rejected"])

    text = result_text(runner.invoke(cli, ["jobs", "summary"]))

    assert "Stages" in text
    assert "1 passed" in _line_with(text, "screening")
    assert "1 rejected" in _line_with(text, "technical")


def test_status_summary_shows_each_stages_pass_rate_with_its_interval(cli_env):
    runner = CliRunner()
    for job in ("job-a", "job-b", "job-c"):
        runner.invoke(cli, ["jobs", "status", job, "applied"])
    runner.invoke(cli, ["jobs", "status", "job-a", "interview:screening"])
    runner.invoke(cli, ["jobs", "status", "job-b", "rejected"])

    text = result_text(runner.invoke(cli, ["jobs", "summary"]))

    application = _line_with(text, "application")
    assert "1/2 passed" in application and "50% (21–79%)" in application
    assert "1 pending" in application
    assert "%" not in _line_with(text, "screening")


def test_status_shows_the_drive_sync_while_it_waits(cli_env, monkeypatch):
    from door.commands import _common as common
    from door.core import lock, progress

    monkeypatch.setattr(lock, "pre_acquire_hook", lambda purpose, jobs_dir: progress.report("Pulling newer data from Google Drive"))
    monkeypatch.setattr(lock, "post_release_hook", lambda purpose, jobs_dir: progress.report("Pushing changes to Google Drive"))
    monkeypatch.setattr(common, "_stdout_is_tty", lambda: True)

    result = CliRunner().invoke(cli, ["jobs", "status", "job-abc", "applied"])

    assert result.exit_code == 0, result_text(result)
    assert "Pulling newer data from Google Drive" in result.output
    assert "Pushing changes to Google Drive" in result.output


def test_status_refuses_a_bad_job_id_before_taking_the_lock(cli_env, monkeypatch):
    from door.core import lock

    synced = []
    monkeypatch.setattr(lock, "pre_acquire_hook", lambda purpose, jobs_dir: synced.append(purpose))

    result = CliRunner().invoke(cli, ["jobs", "status", "Bad/Id", "applied"])

    assert result.exit_code == 1
    assert "invalid job_id" in result_text(result)
    assert synced == []


def test_the_cli_says_on_stderr_when_it_synced_with_drive(cli_env, monkeypatch):
    from door.core import lock, sync

    monkeypatch.setattr(lock, "pre_acquire_hook", lambda purpose, jobs_dir: sync._note("pulled", "Pulled newer data from Google Drive"))
    monkeypatch.setattr(lock, "post_release_hook", lambda purpose, jobs_dir: sync._note("pushed", "Synced to Google Drive"))

    result = CliRunner().invoke(cli, ["jobs", "status", "job-abc", "applied"])

    assert result.exit_code == 0, result_text(result)
    assert "↓ Pulled newer data from Google Drive" in result.stderr
    assert "↑ Synced to Google Drive" in result.stderr
    assert "Google Drive" not in result.stdout


def test_the_cli_says_nothing_about_drive_when_nothing_synced(cli_env):
    result = CliRunner().invoke(cli, ["jobs", "status", "job-abc", "applied"])

    assert "Google Drive" not in result.output


# --------------------------------------------------------------------------- #
# status — what the outcome analysis needs: when, how, what was sent, the ad
# --------------------------------------------------------------------------- #

_AD = "We are looking for a lead data scientist. " * 20


def _ledger(jobs_dir: Path) -> dict:
    return json.loads((jobs_dir / "applications.json").read_text())


def _write_materials(jobs_dir: Path, job_id: str, cv: str = "cv v1") -> Path:
    out = jobs_dir / "output" / job_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "cv.tex").write_text(cv)
    (out / "cover_letter.tex").write_text("letter v1")
    (out / "cv.pdf").write_bytes(b"%PDF cv")
    (out / "posting.json").write_text(json.dumps({"id": job_id, "description": _AD}))
    return out


def test_status_records_when_it_happened(cli_env):
    _write_status_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-1", description=_AD)

    result = CliRunner().invoke(cli, ["jobs", "status", "job-1", "applied", "--at", "2026-06-20"])

    assert result.exit_code == 0, result_text(result)
    entry = _ledger(cli_env.jobs_dir)["job-1"]
    assert entry["history"][0]["at"] == "2026-06-20T00:00:00+00:00"
    assert "logged_at" in entry["history"][0]


def test_status_refuses_a_date_it_cannot_read(cli_env):
    result = CliRunner().invoke(cli, ["jobs", "status", "job-1", "applied", "--at", "yesterday"])

    assert result.exit_code == 1
    assert "YYYY-MM-DD" in result_text(result)
    assert not (cli_env.jobs_dir / "applications.json").exists()


def test_a_backfilled_event_says_the_current_status_stays(cli_env):
    from door.commands import status as status_cmd

    _write_status_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-1", description=_AD)
    status_cmd._set_status_core("job-1", "interview:screening", jobs_dir=cli_env.jobs_dir)

    result = status_cmd._set_status_core("job-1", "applied", jobs_dir=cli_env.jobs_dir, at="2026-06-20")

    assert result["status"] == "applied"
    assert result["current"] == "interview:screening"
    assert result["at"] == "2026-06-20T00:00:00+00:00"


def test_sending_an_application_keeps_a_copy_of_the_materials_sent(cli_env):
    from door.commands import status as status_cmd
    import hashlib

    out = _write_materials(cli_env.jobs_dir, "job-1")

    result = status_cmd._set_status_core("job-1", "applied", jobs_dir=cli_env.jobs_dir)

    assert result["sent_dir"] == str(out / "sent")
    assert (out / "sent" / "cv.tex").read_text() == "cv v1"
    assert (out / "sent" / "posting.json").exists()
    materials = _ledger(cli_env.jobs_dir)["job-1"]["materials"]
    assert materials["cv.tex"] == hashlib.sha256(b"cv v1").hexdigest()
    assert set(materials) == {"cv.tex", "cover_letter.tex", "cv.pdf", "posting.json"}


def test_sending_keeps_the_cv_photo_with_the_materials_and_records_its_hash(cli_env):
    from door.commands import status as status_cmd
    import hashlib

    out = _write_materials(cli_env.jobs_dir, "job-1")
    (out / "photo.jpg").write_bytes(b"jpeg bytes")

    status_cmd._set_status_core("job-1", "applied", jobs_dir=cli_env.jobs_dir)

    assert (out / "sent" / "photo.jpg").read_bytes() == b"jpeg bytes"
    assert _ledger(cli_env.jobs_dir)["job-1"]["materials"]["photo.jpg"] == hashlib.sha256(b"jpeg bytes").hexdigest()


def test_sending_without_a_photo_records_none(cli_env):
    from door.commands import status as status_cmd

    out = _write_materials(cli_env.jobs_dir, "job-1")
    status_cmd._set_status_core("job-1", "applied", jobs_dir=cli_env.jobs_dir)
    assert "photo.jpg" not in _ledger(cli_env.jobs_dir)["job-1"]["materials"] and not (out / "sent" / "photo.jpg").exists()


def test_the_copy_is_taken_once_when_the_application_is_first_sent(cli_env):
    from door.commands import status as status_cmd

    out = _write_materials(cli_env.jobs_dir, "job-1")
    status_cmd._set_status_core("job-1", "applied", jobs_dir=cli_env.jobs_dir)
    (out / "cv.tex").write_text("cv revised after sending")

    result = status_cmd._set_status_core("job-1", "interview:screening", jobs_dir=cli_env.jobs_dir)

    assert "sent_dir" not in result
    assert (out / "sent" / "cv.tex").read_text() == "cv v1"


def test_a_status_before_sending_takes_no_copy(cli_env):
    from door.commands import status as status_cmd

    out = _write_materials(cli_env.jobs_dir, "job-1")

    status_cmd._set_status_core("job-1", "prepared", jobs_dir=cli_env.jobs_dir)

    assert not (out / "sent").exists()
    assert "materials" not in _ledger(cli_env.jobs_dir)["job-1"]


def test_sending_without_the_ad_on_disk_warns(cli_env):
    from door.commands import status as status_cmd

    result = status_cmd._set_status_core("job-1", "applied", jobs_dir=cli_env.jobs_dir)

    assert "no ad text" in result["warning"]
    assert _ledger(cli_env.jobs_dir)["job-1"]["status"] == "applied"  # recorded all the same


def test_a_short_ad_warns_with_its_length(cli_env):
    from door.commands import status as status_cmd

    _write_status_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-1", description="Principal DS, apply now.")

    result = status_cmd._set_status_core("job-1", "rejected", jobs_dir=cli_env.jobs_dir)

    assert "24 characters" in result["warning"]


def test_the_ad_kept_with_the_materials_counts(cli_env):
    from door.commands import status as status_cmd

    _write_materials(cli_env.jobs_dir, "job-1")

    assert "warning" not in status_cmd._set_status_core("job-1", "applied", jobs_dir=cli_env.jobs_dir)


def test_no_ad_warning_before_sending(cli_env):
    from door.commands import status as status_cmd

    assert "warning" not in status_cmd._set_status_core("job-1", "discarded", jobs_dir=cli_env.jobs_dir)


def test_the_cli_prints_the_warning(cli_env):
    result = CliRunner().invoke(cli, ["jobs", "status", "job-1", "applied"])

    assert result.exit_code == 0, result_text(result)
    assert "no ad text" in result_text(result)


def test_picking_applied_asks_when(cli_env, prompts):
    _write_status_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-1", description=_AD)
    prompts.answers.update({"status": "applied", "at": "2026-06-20"})

    result = CliRunner().invoke(cli, ["jobs", "status", "job-1"])

    assert result.exit_code == 0, result_text(result)
    entry = _ledger(cli_env.jobs_dir)["job-1"]
    assert entry["history"][0]["at"] == "2026-06-20T00:00:00+00:00"


def test_status_message_and_core_name_the_job_by_title_and_company(cli_env):
    from cli_utils import write_list_posting

    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "jobindex.h1708816", score=0.9,
                       title="ML Engineer", company="Trustpilot")
    result = CliRunner().invoke(cli, ["jobs", "status", "trustpilot", "discarded"])
    assert result.exit_code == 0, result_text(result)
    assert "ML Engineer — Trustpilot" in result_text(result)
    assert "h1708816" not in result_text(result)


def test_status_core_result_keeps_job_id_and_adds_label(cli_env):
    from cli_utils import write_list_posting
    from door.commands import status as status_cmd

    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "jobindex.h1", score=0.9,
                       title="ML Engineer", company="Trustpilot")
    result = status_cmd._set_status_core("trustpilot", "applied", jobs_dir=cli_env.jobs_dir)
    assert result["job_id"] == "jobindex.h1"
    assert result["label"] == "ML Engineer — Trustpilot"


def test_status_summary_reads_the_postings_once(cli_env, monkeypatch):
    from door.commands import status
    from door.core import selection

    _write_status_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-high", score=0.9)
    walks = []
    real = selection.iter_postings
    monkeypatch.setattr(selection, "iter_postings", lambda jobs_dir: walks.append(jobs_dir) or real(jobs_dir))

    result = status._status_summary_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)

    assert result["pipeline"]["unapplied"] == 1
    assert result["since_last_review"]["new_matches"] == 1
    assert len(walks) == 1


# --------------------------------------------------------------------------- #
# the facts check on a sent status (issue #325)
# --------------------------------------------------------------------------- #
def _invented(cli_env, cv=r"\item Cut churn by 97\%"):
    from door.commands import status as status_cmd  # noqa: F401

    _write_materials(cli_env.jobs_dir, "job-1", cv=cv)
    (cli_env.profile_dir / "cv.md").write_text("Cut churn by 38%.")


@pytest.mark.parametrize("status", ["applied", "interview:screening"])
def test_sending_with_a_figure_not_in_cv_md_warns(cli_env, status):
    from door.commands import status as status_cmd

    _invented(cli_env)
    result = status_cmd._set_status_core("job-1", status, jobs_dir=cli_env.jobs_dir)

    assert "97%" in result["warning"] and "cv.md" in result["warning"]
    assert _ledger(cli_env.jobs_dir)["job-1"]["status"] == status


def test_the_warning_counts_claims_and_names_skills(cli_env):
    from door.commands import status as status_cmd

    _invented(cli_env, cv="\\section{Skills}\nTerraform\n")
    warning = status_cmd._set_status_core("job-1", "applied", jobs_dir=cli_env.jobs_dir)["warning"]
    assert warning.startswith("1 claim(s) in the sent materials are not in your cv.md: Terraform")


def test_the_figure_warning_joins_the_short_ad_warning(cli_env):
    from door.commands import status as status_cmd

    _invented(cli_env)
    (cli_env.jobs_dir / "output" / "job-1" / "posting.json").write_text(json.dumps({"description": "short"}))
    warning = status_cmd._set_status_core("job-1", "applied", jobs_dir=cli_env.jobs_dir)["warning"]
    assert "characters" in warning and "97%" in warning and "; " in warning


def test_clean_materials_add_no_figure_warning(cli_env):
    from door.commands import status as status_cmd

    _invented(cli_env, cv=r"\item Cut churn by 38\%")
    assert "warning" not in status_cmd._set_status_core("job-1", "applied", jobs_dir=cli_env.jobs_dir)


def test_no_figure_warning_before_sending(cli_env):
    from door.commands import status as status_cmd

    _invented(cli_env)
    assert "warning" not in status_cmd._set_status_core("job-1", "prepared", jobs_dir=cli_env.jobs_dir)


def test_no_cv_md_means_no_figure_warning(cli_env):
    from door.commands import status as status_cmd

    _write_materials(cli_env.jobs_dir, "job-1", cv=r"\item Cut churn by 97\%")
    assert "warning" not in status_cmd._set_status_core("job-1", "applied", jobs_dir=cli_env.jobs_dir)


def test_status_summary_in_progress_carries_the_folded_steps(cli_env):
    from door.commands import status as status_cmd
    from door.core import progress
    from door.core.lock import ledger_lock

    with ledger_lock(cli_env.jobs_dir, "run"):
        progress.report("plan", stage="steps", detail="search,discover,follow,collect,match")
        progress.report("search", total=2, site="search", stage="step", outcome="start")
        snapshot = progress.read_progress(cli_env.jobs_dir)
        live = status_cmd._in_progress(cli_env.jobs_dir)

    assert live["steps"] == snapshot["steps"]
    assert live["steps"][0]["name"] == "search" and live["steps"][0]["status"] == "running"


def test_in_progress_steps_is_none_for_a_snapshot_without_them(cli_env):
    import json

    from door.commands import status as status_cmd
    from door.core import progress
    from door.core.lock import ledger_lock

    with ledger_lock(cli_env.jobs_dir, "run"):
        (cli_env.jobs_dir / progress.PROGRESS_NAME).write_text(json.dumps({"message": "old"}))
        live = status_cmd._in_progress(cli_env.jobs_dir)
    assert live["message"] == "old" and live["steps"] is None


def test_the_warning_carries_the_reason_the_tailor_kept_an_item_for(cli_env):
    from door.commands import status as status_cmd
    from door.tailoring import facts

    _invented(cli_env)
    out = cli_env.jobs_dir / "output" / "job-1"
    facts.check(out, cli_env.profile_dir, keep=[{"kind": "number", "value": "97%", "file": "cv", "reason": "from the ad"}])
    warning = status_cmd._set_status_core("job-1", "applied", jobs_dir=cli_env.jobs_dir)["warning"]
    assert "97%" in warning and "from the ad" in warning
