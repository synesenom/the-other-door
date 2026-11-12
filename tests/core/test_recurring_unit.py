"""Something that keeps going wrong (#593): the one failure the app says, so the user sends a report.

A one-off failure the next run retries is said nowhere (docs/design/README.md, principle 8); the same one
again and again is a line at the sidebar's foot until a report is saved or it stops.
"""

from datetime import datetime, timedelta, timezone

import pytest

from door.core import recurring

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


def _run(hours_ago: float, *, sites=(), failed=None) -> dict:
    """A run record that finished `hours_ago`, its sites as ``(site, outcome)``; `failed` the unscored ads (None: no match step)."""
    at = NOW - timedelta(hours=hours_ago)
    return {
        "started_at": (at - timedelta(minutes=5)).isoformat(), "finished_at": at.isoformat(),
        "search": {"sites": [{"site": s, "outcome": o} for s, o in sites]},
        "collect": None,
        "match": None if failed is None else {"failed": list(failed)},
    }


def _line(hours_ago: float, text: str) -> str:
    return f"{(NOW - timedelta(hours=hours_ago)).strftime('%Y-%m-%dT%H:%M:%SZ')} {text}"


def _check(records=(), lines=(), reported_at=None) -> bool:
    return recurring.keeps_going_wrong(list(records), list(lines), reported_at=reported_at, now=NOW)


def test_the_thresholds_are_named_in_one_place():
    assert recurring.SITE_RUNS == 3
    assert recurring.SCORING_RUNS == 2
    assert recurring.TOOL_FAILURES == 3
    assert recurring.TOOL_WINDOW == timedelta(hours=24)


def test_nothing_on_disk_nothing_wrong():
    assert _check() is False


# --------------------------------------------------------------------------- a job site


def test_a_site_that_failed_in_each_of_its_last_three_runs():
    runs = [_run(h, sites=[("thehub", "failed"), ("jobindex", "ok")]) for h in (50, 26, 2)]
    assert _check(runs) is True


def test_error_counts_as_failed_too():
    runs = [_run(50, sites=[("thehub", "error")]), _run(26, sites=[("thehub", "failed")]), _run(2, sites=[("thehub", "error")])]
    assert _check(runs) is True


def test_one_or_two_failed_runs_are_a_one_off():
    assert _check([_run(2, sites=[("thehub", "failed")])]) is False
    assert _check([_run(h, sites=[("thehub", "failed")]) for h in (26, 2)]) is False


def test_a_site_whose_latest_run_is_ok_has_recovered():
    runs = [_run(h, sites=[("thehub", "failed")]) for h in (80, 50, 26)] + [_run(2, sites=[("thehub", "ok")])]
    assert _check(runs) is False


def test_different_sites_failing_once_each_are_not_the_same_site():
    runs = [_run(50, sites=[("thehub", "failed")]), _run(26, sites=[("jobindex", "failed")]), _run(2, sites=[("euraxess", "failed")])]
    assert _check(runs) is False


def test_runs_that_did_not_try_the_site_are_skipped():
    """Resting or not configured is not a try: the last three tries are still three failures."""
    runs = [
        _run(80, sites=[("thehub", "failed")]), _run(50, sites=[("thehub", "failed")]),
        _run(26, sites=[("thehub", "resting")]), _run(20, sites=[("jobindex", "ok")]), _run(2, sites=[("thehub", "failed")]),
    ]
    assert _check(runs) is True


def test_an_empty_site_is_a_flag_not_a_failure():
    assert _check([_run(h, sites=[("thehub", "empty")]) for h in (50, 26, 2)]) is False


# --------------------------------------------------------------------------- scoring


def test_scoring_that_failed_in_each_of_the_last_two_runs():
    assert _check([_run(26, failed=["a.1"]), _run(2, failed=["a.2"])]) is True


def test_scoring_that_failed_once_is_a_one_off():
    assert _check([_run(2, failed=["a.1"])]) is False
    assert _check([_run(26, failed=["a.1"]), _run(2, failed=[])]) is False


def test_a_run_without_a_match_step_does_not_break_the_streak():
    assert _check([_run(50, failed=["a.1"]), _run(26), _run(2, failed=["a.2"])]) is True


# --------------------------------------------------------------------------- the server


def test_a_server_that_stopped_or_would_not_start():
    assert _check(lines=[_line(3, "ERROR app server stopped: Traceback | boom")]) is True
    assert _check(lines=[_line(3, "ERROR app server would not start: spawn ENOENT")]) is True


def test_a_server_crash_long_ago_has_stopped():
    assert _check(lines=[_line(24 * 8, "ERROR app server stopped: boom")]) is False


def test_other_app_lines_are_not_a_crash():
    assert _check(lines=[_line(3, "ERROR app refused rm_rf: not a tool"), _line(2, "ERROR app show timed out: no answer in 60 s")]) is False


# --------------------------------------------------------------------------- a tool


def test_the_same_tool_failing_three_times_within_a_day():
    lines = [_line(h, "ERROR tool show: no posting found") for h in (20, 10, 1)]
    assert _check(lines=lines) is True


def test_two_failures_or_three_of_different_tools_are_a_one_off():
    assert _check(lines=[_line(h, "ERROR tool show: no posting") for h in (10, 1)]) is False
    tools = ("show", "market", "keywords")
    assert _check(lines=[_line(1, f"ERROR tool {t}: lost") for t in tools]) is False


def test_tool_failures_older_than_a_day_do_not_count():
    lines = [_line(h, "ERROR tool show: no posting") for h in (30, 26, 1)]
    assert _check(lines=lines) is False


def test_a_tool_refused_because_the_ledgers_are_busy_did_not_go_wrong():
    busy = [
        "ERROR tool prepare: a run is in progress (started 06:30, pid 4242); try again when it has finished",
        "ERROR tool set_status: another process of The other door is writing the ledgers (find); try again in a moment",
        "ERROR tool prepare: a run is in progress; try again when it has finished",
    ]
    assert _check(lines=[_line(h, t) for h, t in zip((3, 2, 1), busy)]) is False
    assert _check(lines=[_line(h, busy[0]) for h in (3, 2, 1)]) is False


def test_warnings_are_not_failures():
    assert _check(lines=[_line(h, "WARNING tool market: 3 names left as written") for h in (3, 2, 1)]) is False


def test_lines_that_are_not_the_logs_format_are_skipped():
    assert _check(lines=["", "garbage", "not-a-time ERROR app server stopped: x"]) is False


# --------------------------------------------------------------------------- a report clears it


def test_a_saved_report_clears_what_came_before_it():
    runs = [_run(h, sites=[("thehub", "failed")]) for h in (50, 26, 2)]
    lines = [_line(h, "ERROR tool show: x") for h in (5, 4, 3)] + [_line(3, "ERROR app server stopped: x")]
    reported = NOW - timedelta(hours=1)
    assert _check(runs, lines) is True
    assert _check(runs, lines, reported_at=reported) is False


def test_after_a_report_it_counts_again_from_zero():
    reported = NOW - timedelta(hours=30)
    before = [_run(h, sites=[("thehub", "failed")]) for h in (60, 50, 40)]
    after = [_run(h, sites=[("thehub", "failed")]) for h in (26, 2)]
    assert _check(before + after, reported_at=reported) is False
    assert _check(before + after + [_run(1, sites=[("thehub", "failed")])], reported_at=reported) is True


# --------------------------------------------------------------------------- on disk


def test_stamp_and_read_the_report_time(tmp_path):
    assert recurring.reported_at(tmp_path) is None
    recurring.stamp_report(tmp_path, NOW)
    assert (tmp_path / "logs" / "reported_at").is_file()
    assert recurring.reported_at(tmp_path) == NOW


def test_a_report_saved_in_the_same_second_as_the_run_clears_it(tmp_path):
    runs = [{"finished_at": (NOW + timedelta(milliseconds=ms)).isoformat(), "match": {"failed": ["a"]}} for ms in (200, 400)]
    recurring.stamp_report(tmp_path, NOW + timedelta(milliseconds=800))
    assert recurring.check(tmp_path, runs, now=NOW + timedelta(seconds=1)) is False


def test_an_unreadable_stamp_is_no_stamp(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "reported_at").write_text("yesterday-ish")
    assert recurring.reported_at(tmp_path) is None


def test_no_data_folder_no_stamp(tmp_path):
    recurring.stamp_report(tmp_path / "missing", NOW)
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("reported", [False, True])
def test_check_reads_the_log_and_the_stamp_of_the_data_folder(tmp_path, reported):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "door.log").write_text("\n".join(_line(h, "ERROR tool show: x") for h in (3, 2, 1)) + "\n")
    if reported:
        recurring.stamp_report(tmp_path, NOW)
    assert recurring.check(tmp_path, [], now=NOW) is (not reported)


def test_check_without_a_log(tmp_path):
    assert recurring.check(tmp_path, [_run(2, failed=["a"]), _run(1, failed=["b"])], now=NOW) is True
    assert recurring.check(tmp_path, [], now=NOW) is False
