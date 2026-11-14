"""`core/usage.py`: what used the plan this week, and how many runs fit in what is left (#575).

Offline: envelopes are saved shapes of `claude -p --output-format json`; nothing calls `claude`.
"""

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from door.core import usage, workspace


def _envelope(cost=0.01, is_error=False, result="ok"):
    return json.dumps({"type": "result", "is_error": is_error, "result": result, "total_cost_usd": cost,
                       "modelUsage": {"claude-haiku-4-5": {"inputTokens": 100, "outputTokens": 50}}})


def _lines(jobs_dir):
    return [json.loads(line) for line in (jobs_dir / usage.LOG_NAME).read_text().splitlines()]


def _log(jobs_dir, *rows):
    """Write lines straight to the log: (feature, weight, units, days_ago)."""
    now = datetime.now(timezone.utc)
    with (jobs_dir / usage.LOG_NAME).open("a") as fh:
        for feature, weight, units, days_ago in rows:
            at = (now - timedelta(days=days_ago)).isoformat()
            fh.write(json.dumps({"at": at, "feature": feature, "units": units, "weight": weight}) + "\n")


# --------------------------------------------------------------------------- the registry
def test_every_feature_counts_towards_a_known_activity():
    assert set(usage.FEATURES.values()) <= set(usage.BUCKETS)
    assert usage.FEATURES["match_scoring"] == "find" and usage.FEATURES["tailoring"] == "prepare"


# --------------------------------------------------------------------------- reading an envelope
def test_weight_is_the_envelopes_api_price():
    assert usage.weight(_envelope(cost=0.024)) == 0.024


def test_weight_counts_an_error_envelope_too():
    """An error answer still drew on the plan."""
    assert usage.weight(_envelope(cost=0.003, is_error=True)) == 0.003


@pytest.mark.parametrize("stdout", [None, "", "plain text", "[1, 2]", json.dumps({"result": "x"}),
                                    json.dumps({"total_cost_usd": True}), json.dumps({"total_cost_usd": -1})])
def test_weight_is_none_without_one(stdout):
    assert usage.weight(stdout) is None


# --------------------------------------------------------------------------- recording
def test_record_appends_one_line_to_the_jobs_folder(tmp_path):
    usage.record("match_scoring", _envelope(cost=0.02), units=5, jobs_dir=tmp_path)
    [line] = _lines(tmp_path)
    assert (line["feature"], line["units"], line["weight"]) == ("match_scoring", 5, 0.02)
    assert line["at"].endswith("+00:00")
    assert set(line) == {"at", "feature", "units", "weight"}


def test_record_defaults_to_the_workspace_jobs_folder():
    usage.record("ask", _envelope())
    assert _lines(workspace.JOBS_DIR)[0]["feature"] == "ask"


def test_record_skips_output_with_no_weight(tmp_path):
    assert usage.record("ask", "not json", jobs_dir=tmp_path) is None
    assert not (tmp_path / usage.LOG_NAME).exists()


def test_record_refuses_an_unknown_feature(tmp_path):
    with pytest.raises(ValueError, match="unknown"):
        usage.record("nope", _envelope(), jobs_dir=tmp_path)


def test_record_never_raises_on_a_write_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    assert usage.record("ask", _envelope(), jobs_dir=blocker / "jobs") is None


def test_record_from_many_threads_keeps_every_line_whole(tmp_path):
    threads = [threading.Thread(target=usage.record, args=("match_scoring", _envelope()),
                                kwargs={"jobs_dir": tmp_path}) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(_lines(tmp_path)) == 40


def test_read_skips_broken_lines_and_unknown_features(tmp_path):
    usage.record("ask", _envelope(), jobs_dir=tmp_path)
    with (tmp_path / usage.LOG_NAME).open("a") as fh:
        fh.write("{broken\n" + json.dumps({"feature": "gone", "units": 1}) + "\n")
    assert [r["feature"] for r in usage.read(tmp_path)] == ["ask"]


# --------------------------------------------------------------------------- this week
def test_week_gives_each_activity_its_share_heaviest_first(tmp_path):
    _log(tmp_path,
         ("tailoring", 1.40, 1, 1), ("revise", 0.10, 1, 1),          # preparing: 1.50
         ("match_scoring", 0.40, 100, 2), ("title_translation", 0.05, 1, 2),
         ("match_scoring", 0.05, 10, 2),                              # finding: 0.50 (110 postings)
         ("ask", 0.03, 1, 0), ("draft_cv", 0.07, 1, 3),               # everything else: 0.10
         ("tailoring", 9.0, 1, 30))                                   # last month: not this week
    got = usage.week(tmp_path)
    assert got["days"] == 7 and got["heaviest"] == "prepare"
    assert [(a["activity"], a["share"], a["count"], a["of"]) for a in got["activities"]] == [
        ("prepare", 0.714, 1, "applications prepared"),
        ("find", 0.238, 110, "postings scored"),
        ("other", 0.048, 2, "other requests"),
    ]
    assert got["activities"][0]["label"] == "Preparing applications"


def test_week_is_empty_without_calls(tmp_path):
    assert usage.week(tmp_path) == {"days": 7, "activities": [], "heaviest": None}


def test_week_takes_another_window(tmp_path):
    _log(tmp_path, ("ask", 0.01, 1, 20))
    assert usage.week(tmp_path)["activities"] == []
    assert usage.week(tmp_path, days=30)["heaviest"] == "other"


# --------------------------------------------------------------------------- what it cost (#64)
def test_every_feature_has_a_label():
    assert set(usage.FEATURE_LABELS) == set(usage.FEATURES)
    assert all(usage.FEATURE_LABELS.values())


def test_cost_gives_each_activity_its_dollars_and_each_feature_within_it(tmp_path):
    _log(tmp_path,
         ("tailoring", 1.40, 1, 1), ("revise", 0.10, 1, 1),
         ("match_scoring", 0.40, 100, 2), ("title_translation", 0.05, 1, 2), ("match_scoring", 0.05, 10, 2),
         ("ask", 0.03, 1, 0), ("draft_cv", 0.07, 1, 3),
         ("tailoring", 9.0, 1, 30))                                   # last month: outside the window
    got = usage.cost(tmp_path, records=[])
    assert got["days"] == 7 and got["usd"] == pytest.approx(2.10)
    assert [(a["activity"], a["usd"], a["count"], a["of"]) for a in got["activities"]] == [
        ("prepare", pytest.approx(1.50), 1, "applications prepared"),
        ("find", pytest.approx(0.50), 110, "postings scored"),
        ("other", pytest.approx(0.10), 2, "other requests"),
    ]
    find = got["activities"][1]
    assert find["label"] == "Finding jobs"
    assert [(f["feature"], f["usd"], f["calls"]) for f in find["features"]] == [
        ("match_scoring", pytest.approx(0.45), 2), ("title_translation", pytest.approx(0.05), 1)]
    assert find["features"][0]["label"] == usage.FEATURE_LABELS["match_scoring"]


def test_cost_gives_one_find_and_one_prepare_in_dollars(tmp_path):
    _log(tmp_path, ("tailoring", 1.20, 1, 1), ("tailoring", 0.80, 1, 2))
    assert usage.cost(tmp_path, records=[])["per_run"]["prepare"] == pytest.approx(1.0)


def test_cost_takes_another_window(tmp_path):
    _log(tmp_path, ("ask", 0.02, 1, 20))
    assert usage.cost(tmp_path, records=[])["activities"] == []
    assert usage.cost(tmp_path, records=[])["usd"] == 0
    assert usage.cost(tmp_path, days=30, records=[])["usd"] == pytest.approx(0.02)


def test_cost_is_none_before_any_call_was_weighed(tmp_path):
    assert usage.cost(tmp_path) is None
    with (tmp_path / usage.LOG_NAME).open("a") as fh:   # a refused call: a reading, no weight
        fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "feature": "ask", "units": 1,
                             "status": "rejected"}) + "\n")
    assert usage.cost(tmp_path) is None


# --------------------------------------------------------------------------- the plan's limits (plan §5)
_LIMITS = {"status": "allowed",
           "five_hour": {"used": 0.42, "resets_at": 1762182000, "status": "allowed"},
           "seven_day": {"used": 0.31, "resets_at": 1762700000}}


def test_record_writes_each_windows_reading(tmp_path):
    usage.record("match_scoring", _envelope(cost=0.02), units=3, limits=_LIMITS, jobs_dir=tmp_path)
    [line] = _lines(tmp_path)
    assert {k: line[k] for k in ("u5", "r5", "u7", "r7", "status")} == {
        "u5": 0.42, "r5": 1762182000, "u7": 0.31, "r7": 1762700000, "status": "allowed"}


def test_record_writes_only_the_readings_there_are(tmp_path):
    usage.record("ask", _envelope(), limits={"five_hour": {"resets_at": 7}}, jobs_dir=tmp_path)
    [line] = _lines(tmp_path)
    assert set(line) == {"at", "feature", "units", "weight", "r5"}


def test_record_keeps_a_reading_with_no_weight(tmp_path):
    """A refused call may report no cost, but its `rejected` is what the user needs to see."""
    usage.record("ask", "not json", limits={"status": "rejected", "five_hour": {"resets_at": 7}}, jobs_dir=tmp_path)
    [line] = _lines(tmp_path)
    assert (line["status"], line["r5"]) == ("rejected", 7) and "weight" not in line


def _reading(jobs_dir, at, **fields):
    with (jobs_dir / usage.LOG_NAME).open("a") as fh:
        fh.write(json.dumps({"at": at.isoformat(), "feature": "ask", "units": 1, "weight": 0.01, **fields}) + "\n")


_NOW = datetime(2026, 11, 3, 14, 10, tzinfo=timezone.utc)
_LATER = int((_NOW + timedelta(hours=1)).timestamp())


def test_latest_is_the_newest_line_with_a_reading(tmp_path):
    _reading(tmp_path, _NOW - timedelta(minutes=30), u5=0.2, r5=_LATER, status="allowed")
    _reading(tmp_path, _NOW - timedelta(minutes=20), u5=0.3, r5=_LATER, u7=0.5, r7=_LATER + 9, status="allowed_warning")
    _reading(tmp_path, _NOW - timedelta(minutes=10))  # no reading: an old-style line
    assert usage.latest(tmp_path, now=_NOW) == {
        "at": (_NOW - timedelta(minutes=20)).isoformat(), "status": "allowed_warning",
        "five_hour": {"used": 0.3, "resets_at": _LATER},
        "seven_day": {"used": 0.5, "resets_at": _LATER + 9},
    }


def test_a_window_that_has_reset_reads_as_unused(tmp_path):
    past = int((_NOW - timedelta(minutes=5)).timestamp())
    _reading(tmp_path, _NOW - timedelta(hours=2), u5=0.97, r5=past, u7=0.5, r7=_LATER, status="rejected")
    latest = usage.latest(tmp_path, now=_NOW)
    assert latest["five_hour"] == {"used": 0.0}
    assert latest["seven_day"] == {"used": 0.5, "resets_at": _LATER}
    assert "status" not in latest  # it spoke of a window that has since reset


def test_latest_is_none_without_a_reading(tmp_path):
    assert usage.latest(tmp_path, now=_NOW) is None
    _reading(tmp_path, _NOW)
    assert usage.latest(tmp_path, now=_NOW) is None


@pytest.mark.parametrize("fields", [{"u5": "x"}, {"u5": True}, {"r5": "soon"}, {"status": 3}])
def test_latest_ignores_unreadable_fields(tmp_path, fields):
    _reading(tmp_path, _NOW, **fields)
    assert usage.latest(tmp_path, now=_NOW) is None


# --------------------------------------------------------------------------- calibration (plan §6.1)
_T0 = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)
_R1 = int((_T0 + timedelta(hours=4)).timestamp())


def _ln(minutes, feature="match_scoring", weight=0.01, units=1, **fields):
    return {"at": (_T0 + timedelta(minutes=minutes)).isoformat(), "feature": feature, "units": units,
            "weight": weight, **fields}


def _segment(n, *, start=0.10, step=0.004, weight=0.01, reset=_R1, at=0, every=1, short="5"):
    """`n` lines a minute apart whose window rises `step` per line."""
    return [_ln(at + i * every, weight=weight, **{f"u{short}": round(start + i * step, 4), f"r{short}": reset})
            for i in range(n)]


def test_calibration_telescopes_over_a_segment():
    # 24 lines after the first carry 0.24 of weight; the window rose 24 × 0.004 = 0.096 → 0.4 a unit of weight.
    assert usage.calibration(_segment(25), "five_hour") == pytest.approx(0.4)


def test_calibration_leaves_the_first_lines_own_share_out():
    lines = _segment(25)
    lines[0]["weight"] = 100.0  # what the first call itself used is unknown: it is not counted
    assert usage.calibration(lines, "five_hour") == pytest.approx(0.4)


def test_parallel_calls_finishing_out_of_order_still_telescope():
    lines = _segment(25)
    lines[5]["u5"], lines[6]["u5"] = lines[6]["u5"], lines[5]["u5"]
    assert usage.calibration(lines, "five_hour") == pytest.approx(0.4)


def test_a_reset_starts_a_new_segment():
    later = int((_T0 + timedelta(hours=9)).timestamp())
    lines = _segment(15, start=0.80) + _segment(15, start=0.0, reset=later, at=20, step=0.008)
    # (14 × 0.004 + 14 × 0.008) / (28 × 0.01): the fall from 0.86 to 0.0 at the reset is no use
    assert usage.calibration(lines, "five_hour") == pytest.approx((14 * 0.004 + 14 * 0.008) / 0.28)


def test_a_gap_of_over_a_quarter_hour_starts_a_new_segment():
    lines = _segment(15) + _segment(15, start=0.5, at=60)  # the jump during the gap is the user's own chats
    assert usage.calibration(lines, "five_hour") == pytest.approx(0.4)


@pytest.mark.parametrize("lines", [_segment(19), _segment(25, step=0.0005), [], _segment(25, weight=0.0)])
def test_too_little_to_go_on_is_no_calibration(lines):
    assert usage.calibration(lines, "five_hour") is None


def test_calibration_reads_the_latest_lines_only(monkeypatch):
    monkeypatch.setattr(usage, "CALIBRATION_LINES", 30)
    old = _segment(40, step=0.001)
    new = _segment(30, at=100, start=0.2, reset=_R1 + 1)
    assert usage.calibration(old + new, "five_hour") == pytest.approx(0.4)


def test_the_seven_day_window_calibrates_from_its_own_readings():
    assert usage.calibration(_segment(25, short="7", step=0.002), "seven_day") == pytest.approx(0.2)
    assert usage.calibration(_segment(25, short="7"), "five_hour") is None


# --------------------------------------------------------------------------- size of a run (plan §6.2)
def _record(start_min, end_min):
    return {"started_at": (_T0 + timedelta(minutes=start_min)).isoformat(),
            "finished_at": (_T0 + timedelta(minutes=end_min)).isoformat()}


def test_a_find_weighs_what_its_finding_calls_weighed():
    lines = [_ln(1, weight=0.2), _ln(2, "title_translation", weight=0.1), _ln(3, "careers_lookup", weight=0.1),
             _ln(4, "ask", weight=5.0),  # the user asked something meanwhile: not the run's
             _ln(31, weight=0.2)]
    assert usage.run_sizes(lines, [_record(0, 10), _record(30, 40)])["find"] == pytest.approx(0.3)


def test_runs_before_any_calls_were_recorded_are_left_out():
    assert usage.run_sizes([_ln(31, weight=0.2)], [_record(0, 10), _record(30, 40)])["find"] == pytest.approx(0.2)


def test_a_find_reads_the_latest_runs(monkeypatch):
    monkeypatch.setattr(usage, "RUNS", 1)
    lines = [_ln(1, weight=9.0), _ln(31, weight=0.2)]
    assert usage.run_sizes(lines, [_record(0, 10), _record(30, 40)])["find"] == pytest.approx(0.2)


def test_a_prepare_weighs_its_tailoring_calls():
    lines = [_ln(i, "tailoring", weight=w) for i, w in enumerate((9.0, 1.0, 1.4))]
    assert usage.run_sizes(lines, [])["prepare"] == pytest.approx((9.0 + 1.0 + 1.4) / 3)


def test_before_any_history_a_run_is_sized_from_scoring_one_posting():
    lines = [_ln(1, weight=0.04, units=10), _ln(2, weight=0.5, units=0)]  # a failed chunk: no postings, left out
    sizes = usage.run_sizes(lines, [])
    assert sizes == {"find": pytest.approx(usage.DEFAULT_POSTINGS_PER_RUN * 0.004),
                     "prepare": pytest.approx(usage.DEFAULT_PREPARE_WEIGHT * 0.004)}


def test_with_no_measurements_there_is_no_size():
    assert usage.run_sizes([_ln(1, "ask")], [_record(0, 10)]) == {"find": None, "prepare": None}


# --------------------------------------------------------------------------- the answer (plan §6.3)
def _write(jobs_dir, lines):
    with (jobs_dir / usage.LOG_NAME).open("a") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


def _calibrated(jobs_dir, *, status="allowed", u7=True):
    """25 scoring lines (k5 = 0.4, k7 = 0.2), ending at 0.196 / 0.348 used, and two prepares of weight 0.25."""
    lines = _segment(25)
    for i, line in enumerate(lines):
        if u7:
            line.update(u7=round(0.30 + i * 0.002, 4), r7=_R1 + 86400)
        line["status"] = "allowed"
    lines[-1]["status"] = status
    lines += [_ln(26, "tailoring", weight=0.25), _ln(27, "tailoring", weight=0.25)]
    _write(jobs_dir, lines)


_AT = _T0 + timedelta(minutes=30)


def test_no_reading_is_no_answer(tmp_path):
    _write(tmp_path, [_ln(1)])
    assert usage.room(tmp_path, records=[], now=_AT) is None


def test_room_divides_what_is_left_by_a_runs_share(tmp_path):
    _calibrated(tmp_path)
    plan = usage.room(tmp_path, records=[], now=_AT)
    # left: 5-hour (1 − 0.196) / 0.4 = 2.01 of weight, 7-day (1 − 0.348) / 0.2 = 3.26: the 5-hour window binds.
    # a find before any run history: 40 postings × 0.01 = 0.4; a prepare 0.25.
    assert plan["room"] == {"find": 5, "prepare": 8}
    assert plan["binding"] == "five_hour"
    assert plan["five_hour"] == {"used": 0.196, "resets_at": datetime.fromtimestamp(_R1, timezone.utc).isoformat()}
    assert plan["seven_day"]["used"] == 0.348
    assert plan["as_of"] == _ln(24)["at"] and plan["status"] == "allowed"
    assert "warning" not in plan


def test_the_fuller_window_binds(tmp_path):
    _calibrated(tmp_path)
    # after a gap, so the calibration stays k5 = 0.4, k7 = 0.2: left 5-hour 0.8 / 0.4 = 2, 7-day 0.07 / 0.2 = 0.35
    _write(tmp_path, [_ln(40, u5=0.2, r5=_R1, u7=0.93, r7=_R1 + 86400, status="allowed")])
    plan = usage.room(tmp_path, records=[], now=_AT + timedelta(minutes=15))
    assert plan["binding"] == "seven_day" and plan["room"] == {"find": 0, "prepare": 1}


def test_uncalibrated_the_windows_stand_alone(tmp_path):
    _write(tmp_path, [_ln(1, u5=0.42, r5=_R1, status="allowed")])
    plan = usage.room(tmp_path, records=[], now=_AT)
    assert plan["five_hour"]["used"] == 0.42 and plan["room"] is None and plan["binding"] is None


def test_a_window_close_to_its_limit_warns(tmp_path):
    _calibrated(tmp_path, status="allowed_warning")
    assert usage.room(tmp_path, records=[], now=_AT)["warning"] == "Claude's usage limit is close"


def test_a_refused_call_leaves_no_room(tmp_path):
    _calibrated(tmp_path)
    _write(tmp_path, [{"at": _ln(29)["at"], "feature": "ask", "units": 1, "u5": 1.0, "r5": _R1, "status": "rejected"}])
    plan = usage.room(tmp_path, records=[], now=_AT)
    assert plan["room"] == {"find": 0, "prepare": 0}
    assert plan["binding"] == "five_hour" and plan["warning"] == "Claude's usage limit is reached"


def test_without_utilization_only_the_status_and_reset_are_told(tmp_path):
    _write(tmp_path, [_ln(1, r5=_R1, status="allowed")])
    plan = usage.room(tmp_path, records=[], now=_AT)
    assert plan["five_hour"] == {"resets_at": datetime.fromtimestamp(_R1, timezone.utc).isoformat()}
    assert plan["room"] is None


def test_room_reads_the_run_records_itself(tmp_path):
    _calibrated(tmp_path)
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "a.json").write_text(json.dumps(_record(-1, 25)))
    # the one run weighed its 25 scoring lines, 0.25: (1 − 0.196) / 0.4 / 0.25 = 8 finds
    assert usage.room(tmp_path, now=_AT)["room"]["find"] == 8


# --------------------------------------------------------------------------- the tailoring retry
def test_a_tailoring_retry_counts_as_preparing():
    assert usage.FEATURES["tailoring_retry"] == "prepare"


def test_a_retry_is_not_another_application_prepared(tmp_path):
    _log(tmp_path, ("tailoring", 1.0, 1, 1), ("tailoring_retry", 0.5, 1, 1))
    prepare = usage.week(tmp_path)["activities"][0]
    assert prepare["activity"] == "prepare" and prepare["count"] == 1 and prepare["share"] == 1.0


def test_a_prepare_weighs_its_retry_too():
    lines = [_ln(0, "tailoring", weight=1.0), _ln(1, "tailoring", weight=1.0), _ln(2, "tailoring_retry", weight=1.0)]
    assert usage.run_sizes(lines, [])["prepare"] == pytest.approx(1.5)


def test_a_retry_older_than_every_selected_tailoring_is_left_out(monkeypatch):
    monkeypatch.setattr(usage, "PREPARES", 1)
    lines = [_ln(0, "tailoring", weight=1.0), _ln(1, "tailoring_retry", weight=5.0), _ln(2, "tailoring", weight=1.0)]
    assert usage.run_sizes(lines, [])["prepare"] == pytest.approx(1.0)
