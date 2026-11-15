"""The failures a user can act on, the real process on a populated world (#99): a board that fails,
words that match no job, a tailor whose model call fails."""

import pytest

from cli_world import build_world

AD = "vestvind-senior-ds-forecasting"   # not yet prepared on a fresh world
WORDS = "vestvind"


@pytest.fixture(scope="module")
def world():
    return build_world("mette")


def test_find_names_the_board_that_failed_and_exits_2(world):
    runs = world.home / "jobs" / "runs"
    before = set(runs.glob("2*.json"))
    world.set_board("jobindex", fail="jobindex is down")
    try:
        code, out, err = world.door("find")
    finally:
        world.clear_board_fault("jobindex")
    assert code == 2, f"{out}\n{err}"
    assert "jobindex" in out + err
    new = set(runs.glob("2*.json")) - before
    assert len(new) == 1
    record = world.read(f"jobs/runs/{new.pop().name}")
    assert any(s["site"] == "jobindex" and s["outcome"] == "failed" for s in record["search"]["sites"])


def test_jobs_show_with_words_that_match_nothing_says_so(world):
    code, out, err = world.door("jobs", "show", "nonexistent employer")
    assert code != 0
    assert "no job matches" in err
    assert "Traceback" not in out + err


def test_jobs_prepare_reports_a_failed_tailor_and_leaves_the_job_alone(world):
    job = world.jobs[AD]["id"]
    world.faults({"claude": {"tailor": {"fail": "claude: boom"}}})
    try:
        code, out, err = world.door("jobs", "prepare", WORDS)
    finally:
        world.faults({})
    assert code != 0, f"{out}\n{err}"
    assert "tailor step failed" in err
    assert "Traceback" not in out + err
    assert not (world.home / "jobs" / "output" / job / "cv.pdf").exists()
    ledger = world.home / "jobs" / "applications.json"
    status = world.read("jobs/applications.json").get(job, {}).get("status") if ledger.exists() else None
    assert status in (None, "unapplied")
