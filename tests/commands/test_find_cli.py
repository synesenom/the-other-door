"""`find`: the five steps (search, discover, follow, collect, match), the run record and the command.

The steps' cores are faked (`stub_steps`), so nothing here reaches a network or `claude`; each step's
own tests are in tests/pipeline/. The shared `cli_env` fixture is in tests/commands/conftest.py.
"""

import json
import re

import click
import pytest
from click.testing import CliRunner

from door.cli import cli
from door.commands import _common as common
from door.commands import prepare as prepare_cmd
from door.commands import find as find_cmd
from door.core.progress import Progress
from cli_utils import CaptureReporter, result_text, stub_blocks, stub_steps

ALL = ["search", "discover", "follow", "collect", "match"]


def run_core(cli_env, *args, **kw):
    return find_cmd._find_core(*args, jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir, **kw)


# --------------------------------------------------------------------------- #
# _find_core: which steps, in which order, with which options
# --------------------------------------------------------------------------- #

def test_run_core_runs_the_five_steps_in_order(cli_env, monkeypatch):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    record = run_core(cli_env)
    assert steps.order() == ["discover", "search", "follow", "collect", "match"]  # discover begins first, in the background
    assert record["steps"] == ALL and record["skipped"] == {}
    assert all(record[name] is not None for name in ALL)


def test_run_core_with_a_step_runs_just_that_one(cli_env, monkeypatch):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    record = run_core(cli_env, "collect")
    assert steps.order() == ["collect"] and record["steps"] == ["collect"]
    assert record["collect"] is not None and record["search"] is None and record["match"] is None
    assert record["new_above_threshold"] == [] and record["top"] == []


def test_skip_leaves_steps_out_and_says_why(cli_env, monkeypatch, progress_events):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    record = run_core(cli_env, skip=["discover", "collect"])
    assert steps.order() == ["search", "follow", "match"]
    assert record["skipped"] == {"discover": "--skip", "collect": "--skip"} and record["discover"] is None
    skipped = [(e.site, e.detail) for e in progress_events if e.stage == "step" and e.outcome == "skipped"]
    assert skipped == [("discover", "--skip"), ("collect", "--skip")]


def test_a_step_that_skips_itself_is_recorded_as_skipped(cli_env, monkeypatch):
    skipping = {**stub_blocks(cli_env.jobs_dir)["discover"], "skipped": "LinkedIn resting until 14:20"}
    stub_steps(monkeypatch, cli_env.jobs_dir, discover=skipping)
    record = run_core(cli_env)
    assert record["skipped"] == {"discover": "LinkedIn resting until 14:20"} and "discover" not in record["steps"]
    assert record["discover"] == skipping


def test_the_options_go_to_the_steps_they_belong_to(cli_env, monkeypatch):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    run_core(cli_env, boards=["thehub"], companies=["BEC"], dry_run=True)
    calls = dict(steps.calls)
    assert calls["search"]["boards"] == ["thehub"]
    assert calls["collect"]["companies"] == ["BEC"]
    assert calls["follow"]["dry_run"] is True
    assert "progress" not in calls["search"]
    assert all(c["jobs_dir"] == cli_env.jobs_dir and c["profile_dir"] == cli_env.profile_dir for c in calls.values())


@pytest.mark.parametrize("kwargs, message", [
    ({"step": "scrape"}, "unknown step 'scrape'"),
    ({"skip": ["bogus"]}, "unknown step 'bogus'"),
    ({"step": "match", "skip": ["search"]}, "cannot go with a single step"),
])
def test_run_core_refuses_nonsense(cli_env, monkeypatch, kwargs, message):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    step = kwargs.pop("step", None)
    with pytest.raises(ValueError, match=message):
        run_core(cli_env, step, **kwargs)
    assert steps.calls == []


def test_run_core_missing_config_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_cmd._find_core(jobs_dir=tmp_path / "jobs", profile_dir=tmp_path / "no_profile")


def test_a_failing_step_stops_the_run_and_writes_no_record(cli_env, monkeypatch):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    monkeypatch.setattr("door.pipeline.collect._collect_core", lambda **kw: (_ for _ in ()).throw(ValueError("not followed")))
    with pytest.raises(ValueError, match="not followed"):
        run_core(cli_env)
    assert steps.order() == ["discover", "search", "follow"] and not (cli_env.jobs_dir / "runs").exists()
    [handle] = steps.handles
    assert handle.cancelled and handle.finished  # LinkedIn is stopped and what it read is kept


# --------------------------------------------------------------------------- #
# discover in the background, and the late follow and collect
# --------------------------------------------------------------------------- #

def found(cli_env, steps, n=3, followed=("Pleo",)):
    steps.blocks["discover"] = {**steps.blocks["discover"], "employers": n, "queued": n, "summary": f"{n} employers, {n} queued"}
    steps.blocks["follow"] = {**steps.blocks["follow"], "followed": [{"company": c, "platform": "lever", "entry": c.lower()} for c in followed],
                              "checked": 2, "summary": "2 candidates: 0 followed", "results": []}


def test_discover_starts_first_and_is_settled_after_collect_with_a_late_follow_and_collect(cli_env, monkeypatch):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    found(cli_env, steps)

    record = run_core(cli_env)

    assert steps.order() == ["discover", "search", "follow", "collect", "follow", "collect", "match"]
    late_follow, late_collect = steps.calls[4][1], steps.calls[5][1]
    assert late_follow["late"] is True and late_collect["late"] is True and late_collect["companies"] == ["Pleo"]
    assert record["steps"] == ALL and record["follow"]["late"]["summary"] and record["collect"]["late"]["summary"]
    assert record["follow"]["summary"] == "2 candidates: 0 followed + late: 2 candidates: 0 followed"
    assert record["collect"]["summary"] == "no followed employers + late: no followed employers"
    assert record["follow"]["followed"] == steps.blocks["follow"]["followed"] * 2  # both passes' employers


def test_the_late_passes_are_folded_into_the_blocks_so_failures_and_counts_include_them(cli_env, monkeypatch):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    found(cli_env, steps)
    steps.blocks["collect"] = {**steps.blocks["collect"], "employers": 4, "postings": 10, "failed": 1,
                               "sites": [{"site": "lever", "outcome": "ok", "count": 10}]}
    record = run_core(cli_env)
    assert record["collect"]["employers"] == 8 and record["collect"]["postings"] == 20 and record["collect"]["failed"] == 2
    assert len(record["collect"]["sites"]) == 2


def test_no_late_pass_when_discover_found_no_employers(cli_env, monkeypatch):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    run_core(cli_env)
    assert steps.order() == ["discover", "search", "follow", "collect", "match"]


def test_discover_done_before_follow_needs_no_late_pass(cli_env, monkeypatch):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    found(cli_env, steps)
    steps.discover_ready = True
    run_core(cli_env)
    assert steps.order() == ["discover", "search", "follow", "collect", "match"]
    assert steps.handles[0].finished


def test_discover_done_after_follow_gets_a_late_follow_but_collect_still_to_come(cli_env, monkeypatch):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    found(cli_env, steps)
    steps.on_call = lambda name: setattr(steps, "discover_ready", name == "follow")  # LinkedIn ends while follow runs
    run_core(cli_env)
    assert steps.order() == ["discover", "search", "follow", "follow", "collect", "match"]
    assert steps.handles[0].finished


def test_a_resting_discover_never_starts_a_background_run(cli_env, monkeypatch):
    skipping = {**stub_blocks(cli_env.jobs_dir)["discover"], "skipped": "LinkedIn resting until 14:20"}
    steps = stub_steps(monkeypatch, cli_env.jobs_dir, discover=skipping)
    record = run_core(cli_env)
    assert steps.order() == ["discover", "search", "follow", "collect", "match"]
    assert record["skipped"] == {"discover": "LinkedIn resting until 14:20"} and record["discover"] == skipping


def test_skipping_follow_skips_the_late_follow_too(cli_env, monkeypatch):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    found(cli_env, steps)
    run_core(cli_env, skip=["follow"])
    assert steps.order() == ["discover", "search", "collect", "match"]


def test_a_dry_run_has_a_late_follow_but_no_late_collect(cli_env, monkeypatch):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    found(cli_env, steps)
    run_core(cli_env, dry_run=True)
    assert steps.order() == ["discover", "search", "follow", "collect", "follow", "match"]


def test_a_collect_limited_to_some_employers_has_no_late_collect(cli_env, monkeypatch):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    found(cli_env, steps)
    run_core(cli_env, companies=["BEC"])
    assert steps.order() == ["discover", "search", "follow", "collect", "follow", "match"]


def test_match_waits_for_discover_when_collect_is_skipped(cli_env, monkeypatch):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    found(cli_env, steps)
    run_core(cli_env, skip=["collect"])
    assert steps.order() == ["discover", "search", "follow", "follow", "match"] and steps.handles[0].finished


def test_a_single_discover_runs_in_the_foreground(cli_env, monkeypatch):
    steps = stub_steps(monkeypatch, cli_env.jobs_dir)
    run_core(cli_env, "discover")
    assert steps.order() == ["discover"] and steps.handles == []


# --------------------------------------------------------------------------- #
# the record
# --------------------------------------------------------------------------- #

def test_run_core_writes_one_record_with_a_block_per_step(cli_env, monkeypatch):
    stub_steps(monkeypatch, cli_env.jobs_dir)
    result = run_core(cli_env)
    [file] = (cli_env.jobs_dir / "runs").glob("*.json")
    record = json.loads(file.read_text())
    assert set(record) == {"started_at", "finished_at", "elapsed_s", "steps", "skipped", *ALL,
                           "new_above_threshold", "top", "failures", "unsure_on"}
    assert record == result
    assert record["search"]["summary"] == "1 postings from 1 boards"


def test_a_single_step_record_has_only_that_block(cli_env, monkeypatch):
    stub_steps(monkeypatch, cli_env.jobs_dir)
    run_core(cli_env, "follow")
    [file] = (cli_env.jobs_dir / "runs").glob("*.json")
    record = json.loads(file.read_text())
    assert record["steps"] == ["follow"] and record["follow"] and not record["search"]


def test_a_follow_dry_run_writes_no_record(cli_env, monkeypatch):
    stub_steps(monkeypatch, cli_env.jobs_dir)
    run_core(cli_env, "follow", dry_run=True)
    assert not (cli_env.jobs_dir / "runs").exists()


def test_the_log_line_summarises_the_steps_that_ran(cli_env, monkeypatch):
    stub_steps(monkeypatch, cli_env.jobs_dir)
    run_core(cli_env)
    run_core(cli_env, "collect")
    lines = (cli_env.jobs_dir / "runs" / "latest.log").read_text().strip().splitlines()
    assert len(lines) == 2
    first = lines[0]
    assert " ok " in first and "1 scraped, 1 scored, 0 new >= 0.65, 0 failures" in first
    assert "search: 1 postings from 1 boards; discover: 0 employers, 0 read, 0 queued; follow: nothing to check" in first
    assert "collect: no followed employers; match: 1 scored, 0 above 0.65" in first
    assert lines[1].endswith("collect: no followed employers") and "search:" not in lines[1]


def test_the_record_and_the_log_line_name_the_unsure_sources_that_are_on(cli_env, monkeypatch):
    from profile_utils import write_config

    write_config(cli_env.profile_dir, {"role_targets": ["data scientist"], "location": "Copenhagen", "linkedin_discovery": True})
    stub_steps(monkeypatch, cli_env.jobs_dir)
    record = run_core(cli_env)
    assert record["unsure_on"] == ["LinkedIn"]
    [line] = (cli_env.jobs_dir / "runs" / "latest.log").read_text().splitlines()
    assert line.endswith("; unsure sources on: LinkedIn")


def test_a_run_with_no_unsure_source_on_says_nothing_of_them(cli_env, monkeypatch):
    stub_steps(monkeypatch, cli_env.jobs_dir)
    record = run_core(cli_env)
    assert record["unsure_on"] == []
    assert "unsure" not in (cli_env.jobs_dir / "runs" / "latest.log").read_text()


def test_scraped_counts_the_postings_of_search_and_collect(cli_env, monkeypatch):
    blocks = stub_blocks(cli_env.jobs_dir)
    collect = {**blocks["collect"], "sites": [{"site": "lever", "outcome": "ok", "count": 6, "dir": "x"}]}
    stub_steps(monkeypatch, cli_env.jobs_dir, collect=collect)
    assert " 7 scraped, " in find_cmd._format_run_summary(run_core(cli_env), 0.65)


def test_failures_are_failed_sites_of_search_and_collect_and_unscored_postings(cli_env, monkeypatch):
    blocks = stub_blocks(cli_env.jobs_dir)
    search = {**blocks["search"], "sites": [{"site": "jobindex", "outcome": "ok", "count": 1},
                                           {"site": "thehub", "outcome": "error", "error": "boom"}]}
    collect = {**blocks["collect"], "sites": [{"site": "lever", "outcome": "failed", "count": 0, "errors": ["404"]},
                                              {"site": "ashby", "outcome": "empty", "warning": "w"}]}
    match = {**blocks["match"], "failed": ["job-x"]}
    stub_steps(monkeypatch, cli_env.jobs_dir, search=search, collect=collect, match=match)
    assert run_core(cli_env)["failures"] == ["thehub", "lever", "job-x"]


def test_new_matches_and_the_top_come_from_the_match_step(cli_env, monkeypatch):
    top = [{"id": "job-a", "score": 0.9, "title": "DS", "company": "Acme"}]
    match = {**stub_blocks(cli_env.jobs_dir)["match"], "new_above_threshold": ["job-a"], "top": top}
    stub_steps(monkeypatch, cli_env.jobs_dir, match=match)
    record = run_core(cli_env)
    assert record["new_above_threshold"] == ["job-a"] and record["top"] == top


def test_format_elapsed_formats_minutes_and_seconds():
    assert common._format_elapsed(252) == "4m12s"
    assert common._format_elapsed(5) == "0m5s"


def test_run_record_filename_is_filesystem_safe():
    name = find_cmd._run_record_filename("2026-09-23T06:30:00.123456+00:00")
    assert "/" not in name and ":" not in name and name.endswith(".json")


# --------------------------------------------------------------------------- #
# --and-prepare
# --------------------------------------------------------------------------- #

def test_run_core_announces_the_plan_first(cli_env, monkeypatch):
    stub_steps(monkeypatch, cli_env.jobs_dir)
    cap = CaptureReporter()
    run_core(cli_env, progress=cap)
    assert cap.events[0] == Progress("plan", stage="steps", detail=",".join(ALL))


def test_a_single_step_plan_is_that_step(cli_env, monkeypatch):
    stub_steps(monkeypatch, cli_env.jobs_dir)
    cap = CaptureReporter()
    run_core(cli_env, "match", progress=cap)
    assert cap.events[0].detail == "match"


def test_events_of_the_steps_reach_the_run_reporter(cli_env, monkeypatch):
    from door.core import progress

    stub_steps(monkeypatch, cli_env.jobs_dir)
    monkeypatch.setattr("door.pipeline.collect._collect_core", lambda **kw: progress.report("deep event") or stub_blocks(cli_env.jobs_dir)["collect"])
    cap = CaptureReporter()
    run_core(cli_env, progress=cap)
    assert "deep event" in [e.message for e in cap.events]


# --------------------------------------------------------------------------- #
# the command
# --------------------------------------------------------------------------- #

def invoke(*args):
    return CliRunner().invoke(cli, ["find", *args])


@pytest.fixture
def steps(cli_env, monkeypatch):
    return stub_steps(monkeypatch, cli_env.jobs_dir)


def test_bare_run_runs_everything_and_prints_a_line_per_step_then_the_summary(cli_env, steps):
    result = invoke()
    assert result.exit_code == 0, result_text(result)
    lines = result.output.strip().splitlines()
    assert lines[0].startswith("[1/5] search: 1 postings from 1 boards (")
    # the lines come as the steps end: discover works beside the others and is settled after collect
    assert [l.split(":")[0] for l in lines[:5]] == ["[1/5] search", "[3/5] follow", "[4/5] collect", "[2/5] discover", "[5/5] match"]
    assert " ok 1 scraped, 1 scored" in lines[5] and len(lines) == 6
    assert steps.order() == ["discover", "search", "follow", "collect", "match"]


def test_on_a_terminal_the_five_lines_are_drawn(cli_env, steps, monkeypatch):
    monkeypatch.setattr(find_cmd, "_stdout_is_tty", lambda: True)
    result = invoke()
    text = result_text(result)
    assert result.exit_code == 0, text
    assert "✓ search" in text and "✓ match" in text and "○ discover" in text
    assert " ok 1 scraped" not in text  # the log line is for --quiet / a pipe; the Top matches end a terminal run


def test_skip_option_takes_step_names(cli_env, steps):
    result = invoke("--skip", "discover,collect")
    assert result.exit_code == 0, result_text(result)
    assert steps.order() == ["search", "follow", "match"]
    assert "[2/5] discover: skipped (--skip)" in result.output
    bad = invoke("--skip", "bogus")
    assert bad.exit_code == 2 and "unknown step(s): bogus" in result_text(bad)


@pytest.mark.parametrize("args, step, expected", [
    (["search", "--boards", "jobindex,thehub"], "search", {"boards": ["jobindex", "thehub"]}),
    (["discover"], "discover", {}),
    (["follow", "--dry-run"], "follow", {"dry_run": True}),
    (["collect", "--company", "BEC", "--company", "Pleo"], "collect", {"companies": ["BEC", "Pleo"]}),
    (["match"], "match", {}),
])
def test_each_step_is_a_subcommand_with_its_own_options(cli_env, steps, args, step, expected):
    result = invoke(*args)
    assert result.exit_code == 0, result_text(result)
    assert steps.order() == [step]
    kwargs = steps.calls[0][1]
    assert {k: kwargs[k] for k in expected} == expected


def test_group_options_come_before_the_step(cli_env, steps):
    result = invoke("--boards", "thehub", "search")
    assert result.exit_code == 0, result_text(result)
    assert steps.calls[0][1]["boards"] == ["thehub"]


def test_boards_on_the_full_run_go_to_search(cli_env, steps):
    result = invoke("--boards", "jobindex,thehub")
    assert result.exit_code == 0, result_text(result)
    assert dict(steps.calls)["search"]["boards"] == ["jobindex", "thehub"]


def test_a_single_step_prints_its_line_and_no_totals(cli_env, steps):
    result = invoke("collect")
    assert result.output.strip().splitlines() == [result.output.strip().splitlines()[0]]
    assert result.output.startswith("[1/1] collect: no followed employers (")


def test_exit_2_on_a_failed_site(cli_env, monkeypatch):
    blocks = stub_blocks(cli_env.jobs_dir)
    search = {**blocks["search"], "sites": [{"site": "jobindex", "outcome": "error", "error": "boom"}]}
    stub_steps(monkeypatch, cli_env.jobs_dir, search=search)
    assert invoke().exit_code == 2


def test_exit_2_also_for_a_failed_employer_platform(cli_env, monkeypatch):
    collect = {**stub_blocks(cli_env.jobs_dir)["collect"],
               "sites": [{"site": "lever", "outcome": "failed", "count": 0, "dir": "x", "errors": ["404 Not Found"]}]}
    stub_steps(monkeypatch, cli_env.jobs_dir, collect=collect)
    assert invoke().exit_code == 2


def test_exit_1_on_unscored_postings_and_the_site_failure_wins(cli_env, monkeypatch):
    blocks = stub_blocks(cli_env.jobs_dir)
    match = {**blocks["match"], "failed": ["job-x"]}
    stub_steps(monkeypatch, cli_env.jobs_dir, match=match)
    result = invoke()
    assert result.exit_code == 1 and "Resume with: ./door find match" in result_text(result)
    search = {**blocks["search"], "sites": [{"site": "jobindex", "outcome": "error", "error": "boom"}]}
    stub_steps(monkeypatch, cli_env.jobs_dir, search=search, match=match)
    assert invoke().exit_code == 2


def test_a_config_error_is_a_clean_exit_1(tmp_path, monkeypatch):
    from door.core import workspace

    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "no_profile")
    monkeypatch.setattr(workspace, "JOBS_DIR", tmp_path / "jobs")
    result = invoke()
    assert result.exit_code == 1 and "config.json" in result_text(result)


def test_an_unknown_board_is_a_clean_exit_1(cli_env, monkeypatch):
    result = invoke("search", "--boards", "greenhouse")
    assert result.exit_code == 1 and "unknown board(s): greenhouse" in result_text(result)


def test_follow_dry_run_prints_what_it_would_record(cli_env, monkeypatch):
    follow = {**stub_blocks(cli_env.jobs_dir)["follow"], "dry_run": True, "checked": 3, "results": [
        {"company": "Pleo", "status": "followed", "platform": "ashby", "entry": "pleo", "reason": None, "error": None},
        {"company": "Danske", "status": "unfollowable", "platform": "oracle_hcm", "entry": None, "reason": "Oracle terms", "error": None},
        {"company": "Acme", "status": "unresolved", "platform": None, "entry": None, "reason": "no job feed found", "error": None},
    ]}
    stub_steps(monkeypatch, cli_env.jobs_dir, follow=follow)
    result = invoke("follow", "--dry-run")
    text = result_text(result)
    assert result.exit_code == 0, text
    assert "Pleo: ashby:pleo (would record)" in text and "Danske: unfollowable - Oracle terms (would record)" in text
    assert "Acme: unresolved - no job feed found" in text
    assert not (cli_env.jobs_dir / "runs").exists()


def _top(job_id="job-a", **kw):
    return {"id": job_id, "score": 0.9, "title": "Data Scientist", "company": "Acme",
            "location": "Copenhagen", **kw}


def _tty_text(cli_env, monkeypatch, *args, **blocks):
    stub_steps(monkeypatch, cli_env.jobs_dir, **blocks)
    monkeypatch.setattr(find_cmd, "_stdout_is_tty", lambda: True)
    return click.unstyle(result_text(invoke(*args)))


def test_the_top_matches_and_site_problems_are_listed_on_a_terminal(cli_env, monkeypatch):
    blocks = stub_blocks(cli_env.jobs_dir)
    collect = {**blocks["collect"], "sites": [{"site": "lever", "outcome": "failed", "count": 0, "dir": "x", "errors": ["404 Not Found"]}]}
    match = {**blocks["match"], "top": [_top()], "new_above_threshold": ["job-a"]}
    text = _tty_text(cli_env, monkeypatch, collect=collect, match=match)
    assert "Top matches" in text and "1 match ≥ 0.65" in text
    assert re.search(r"█+░* 0\.90\s+Data Scientist · Acme · Copenhagen", text), text
    assert "./door jobs show " in text and "./door jobs prepare " in text and "./door jobs list" in text
    assert "./door doctor --probe" in text
    assert "lever: 0 posting(s), 404 x1" in text


def test_more_matches_than_the_top_ten_say_how_many(cli_env, monkeypatch):
    match = {**stub_blocks(cli_env.jobs_dir)["match"], "top": [_top()], "new_above_threshold": [f"job-{i}" for i in range(25)]}
    assert "top 1 of 25" in _tty_text(cli_env, monkeypatch, match=match)


def test_no_matches_says_so_and_points_at_the_list(cli_env, monkeypatch):
    text = _tty_text(cli_env, monkeypatch)
    assert "No matches at or above 0.65" in text
    assert "./door jobs show " not in text and "./door jobs list" in text

