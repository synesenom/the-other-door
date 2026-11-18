"""Unit tests for tracker.py — pure offline, no network.

Tests cover:
- set_status() raises ValueError for unknown statuses
- DuplicateApplicationError raised when applying twice to same job
- Transitions from "applied" to other statuses are allowed
- set_status() updates internal data
- save() / load round-trip and atomicity
- load from missing file starts empty
- load from corrupt file starts empty
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from door.core.jobs.tracker import (
    ApplicationTracker,
    DuplicateApplicationError,
    is_actionable,
)


_NOW = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _tracker(tmp_path: Path) -> ApplicationTracker:
    """Build an ApplicationTracker backed by a tmp file."""
    return ApplicationTracker(tmp_path / "applications.json")


# --------------------------------------------------------------------------- #
# set_status — invalid statuses rejected
# --------------------------------------------------------------------------- #

def test_set_status_unknown_status_message_contains_status(tmp_path):
    tracker = _tracker(tmp_path)
    with pytest.raises(ValueError, match="hired"):
        tracker.set_status("job-abc", "hired")


# --------------------------------------------------------------------------- #
# DuplicateApplicationError — double-apply detection
# --------------------------------------------------------------------------- #

def test_duplicate_application_raises(tmp_path):
    """Calling set_status("applied") twice on the same job raises DuplicateApplicationError."""
    tracker = _tracker(tmp_path)
    tracker.set_status("job-abc", "applied")
    with pytest.raises(DuplicateApplicationError):
        tracker.set_status("job-abc", "applied")


def test_duplicate_application_error_is_value_error(tmp_path):
    """DuplicateApplicationError must be a subclass of ValueError."""
    assert issubclass(DuplicateApplicationError, ValueError)


def test_duplicate_different_jobs_no_error(tmp_path):
    """Applying to two different jobs with status 'applied' is fine."""
    tracker = _tracker(tmp_path)
    tracker.set_status("job-abc", "applied")
    tracker.set_status("job-xyz", "applied")  # different job_id — must not raise


# --------------------------------------------------------------------------- #
# set_status — transitions from "applied" to other statuses
# --------------------------------------------------------------------------- #

def test_other_transitions_from_applied_are_allowed(tmp_path):
    """Going from 'applied' to 'interview' must not raise."""
    tracker = _tracker(tmp_path)
    tracker.set_status("job-abc", "applied")
    tracker.set_status("job-abc", "interview:screening")  # must not raise


def test_ghosted_is_a_status_after_an_interview(tmp_path):
    """The company went silent mid-process: 'ghosted', not 'rejected'."""
    tracker = _tracker(tmp_path)
    tracker.set_status("job-abc", "interview:screening")
    tracker.set_status("job-abc", "ghosted", notes="no reply after the second interview")
    assert tracker._data["job-abc"]["status"] == "ghosted"


# --------------------------------------------------------------------------- #
# set_status — internal data updates
# --------------------------------------------------------------------------- #

def test_set_status_overwrites_previous_status(tmp_path):
    tracker = _tracker(tmp_path)
    tracker.set_status("job-abc", "unapplied")
    tracker.set_status("job-abc", "interview:screening")
    assert tracker._data["job-abc"]["status"] == "interview:screening"


# --------------------------------------------------------------------------- #
# save() / load round-trip
# --------------------------------------------------------------------------- #

def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "applications.json"
    tracker = ApplicationTracker(path)
    tracker.set_status("job-abc", "unapplied")
    tracker.set_status("job-xyz", "applied")
    tracker.save()

    # New instance, load from disk
    tracker2 = ApplicationTracker(path)
    assert tracker2._data["job-abc"]["status"] == "unapplied"
    assert tracker2._data["job-xyz"]["status"] == "applied"


def test_save_atomic_no_tmp_left(tmp_path):
    path = tmp_path / "applications.json"
    tracker = ApplicationTracker(path)
    tracker.set_status("job-abc", "unapplied")
    tracker.save()

    assert list(tmp_path.iterdir()) == [path], "no temp file should be left after an atomic save"


def test_save_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "dir" / "applications.json"
    tracker = ApplicationTracker(path)
    tracker.set_status("job-abc", "unapplied")
    tracker.save()
    assert path.exists()


# --------------------------------------------------------------------------- #
# load — error handling
# --------------------------------------------------------------------------- #

def test_load_missing_file_starts_empty(tmp_path):
    path = tmp_path / "nonexistent_applications.json"
    tracker = ApplicationTracker(path)
    assert tracker.job_ids() == []


def test_load_corrupt_file_starts_empty(tmp_path):
    path = tmp_path / "applications.json"
    path.write_text("BAD JSON")
    tracker = ApplicationTracker(path)
    assert tracker.job_ids() == [] and tracker.get_status("job-abc") is None


# --------------------------------------------------------------------------- #
# set_status — updated_at timestamp (issue #66)
# --------------------------------------------------------------------------- #

def test_set_status_records_updated_at(tmp_path):
    tracker = _tracker(tmp_path)
    tracker.set_status("job-abc", "unapplied", now=_NOW)
    assert tracker.updated_at("job-abc") == _NOW.isoformat()


def test_set_status_defaults_now_when_not_given(tmp_path):
    tracker = _tracker(tmp_path)
    tracker.set_status("job-abc", "unapplied")
    assert "updated_at" in tracker._data["job-abc"]


# --------------------------------------------------------------------------- #
# advance() — lifecycle helper (issue #69)
# --------------------------------------------------------------------------- #

def test_advance_sets_status_and_updated_at(tmp_path):
    tracker = _tracker(tmp_path)
    tracker.advance("job-abc", "prepared", now=_NOW)
    assert tracker.get_status("job-abc") == "prepared"
    assert tracker.updated_at("job-abc") == _NOW.isoformat()


# --------------------------------------------------------------------------- #
# is_actionable() — selection/list contract (issue #69)
# --------------------------------------------------------------------------- #

def test_is_actionable_none_is_true():
    assert is_actionable(None) is True


def test_is_actionable_new_is_true():
    assert is_actionable("unapplied") is True


def test_is_actionable_prepared_is_false():
    assert is_actionable("prepared") is False


# --------------------------------------------------------------------------- #
# history and interview rounds
# --------------------------------------------------------------------------- #

def _at(day: int) -> datetime:
    return datetime(2026, 10, day, 12, 0, 0, tzinfo=timezone.utc)


def test_the_statuses_are_one_list_with_a_status_per_interview_kind():
    from door.core.jobs.tracker import STATUSES

    assert STATUSES == (
        "unapplied", "prepared", "applied",
        "interview:screening", "interview:impression", "interview:assessment", "interview:technical",
        "ghosted", "rejected", "offer", "discarded",
    )


def test_an_interview_without_its_kind_is_refused(tmp_path):
    with pytest.raises(ValueError, match="interview:screening"):
        _tracker(tmp_path).set_status("job-abc", "interview")


def test_every_status_change_is_kept_in_the_history(tmp_path):
    tracker = _tracker(tmp_path)
    tracker.set_status("job-abc", "applied", now=_at(1))
    tracker.set_status("job-abc", "interview:screening", notes="recruiter call", now=_at(5))
    tracker.set_status("job-abc", "interview:technical", now=_at(9))

    assert tracker.history("job-abc") == [
        {"status": "applied", "at": _at(1).isoformat()},
        {"status": "interview:screening", "at": _at(5).isoformat(), "notes": "recruiter call"},
        {"status": "interview:technical", "at": _at(9).isoformat()},
    ]
    assert tracker.get_status("job-abc") == "interview:technical"


def test_the_history_survives_a_save(tmp_path):
    tracker = _tracker(tmp_path)
    tracker.set_status("job-abc", "interview:assessment", now=_at(2))
    tracker.save()

    assert ApplicationTracker(tmp_path / "applications.json").history("job-abc") == [
        {"status": "interview:assessment", "at": _at(2).isoformat()},
    ]


def test_an_entry_without_a_history_starts_it_from_its_last_status(tmp_path):
    import json

    (tmp_path / "applications.json").write_text(json.dumps(
        {"job-abc": {"status": "applied", "updated_at": _at(1).isoformat()}}
    ))
    tracker = _tracker(tmp_path)
    tracker.set_status("job-abc", "interview:screening", now=_at(3))

    assert [e["status"] for e in tracker.history("job-abc")] == ["applied", "interview:screening"]


def _ledger(*statuses_per_job):
    tracker = ApplicationTracker(Path("/nonexistent/applications.json"))
    for n, statuses in enumerate(statuses_per_job):
        for day, status in enumerate(statuses, start=1):
            tracker.set_status(f"job-{n}", status, now=_at(day))
    return tracker


def test_interview_outcomes_count_each_kind_by_how_it_went():
    from door.core.jobs.tracker import interview_outcomes

    tracker = _ledger(
        ["interview:screening", "interview:technical", "rejected"],
        ["interview:screening", "interview:impression", "interview:technical", "offer"],
        ["interview:screening", "ghosted"],
        ["interview:screening"],
        ["applied", "rejected"],
    )

    assert interview_outcomes(tracker) == {
        "screening": {"passed": 2, "rejected": 0, "ghosted": 1, "withdrawn": 0, "pending": 1},
        "impression": {"passed": 1, "rejected": 0, "ghosted": 0, "withdrawn": 0, "pending": 0},
        "technical": {"passed": 1, "rejected": 1, "ghosted": 0, "withdrawn": 0, "pending": 0},
    }


def test_interview_rounds_list_each_round_with_its_result_and_notes():
    tracker = ApplicationTracker(Path("/nonexistent/applications.json"))
    tracker.set_status("job-a", "interview:screening", notes="HR call", now=_at(1))
    tracker.set_status("job-a", "interview:technical", notes="SQL live coding", now=_at(5))
    tracker.set_status("job-a", "rejected", notes="too little Spark", now=_at(8))

    assert tracker.interview_rounds("job-a") == [
        {"stage": "screening", "result": "passed", "at": _at(1).isoformat(), "notes": ["HR call"]},
        {"stage": "technical", "result": "rejected", "at": _at(5).isoformat(),
         "notes": ["SQL live coding", "too little Spark"]},
    ]


def test_the_timeline_is_every_change_with_each_interview_rounds_result():
    tracker = ApplicationTracker(Path("/nonexistent/applications.json"))
    tracker.set_status("job-a", "prepared", now=_at(1))
    tracker.set_status("job-a", "applied", notes="via referral", now=_at(2))
    tracker.set_status("job-a", "interview:screening", now=_at(5))
    tracker.set_status("job-a", "rejected", notes="too junior a team", now=_at(9))

    assert tracker.timeline("job-a") == [
        {"status": "prepared", "at": _at(1).isoformat()},
        {"status": "applied", "at": _at(2).isoformat(), "notes": "via referral"},
        {"status": "interview:screening", "at": _at(5).isoformat(), "result": "rejected"},
        {"status": "rejected", "at": _at(9).isoformat(), "notes": "too junior a team"},
    ]


def test_the_application_stage_counts_every_sent_application_by_how_it_went():
    from door.core.jobs.tracker import application_outcomes

    tracker = _ledger(
        ["applied", "rejected"],
        ["applied", "interview:screening", "interview:impression", "ghosted"],
        ["applied"],
        ["interview:screening"],  # an interview without an applied event was sent all the same
        ["applied", "ghosted"],
        ["applied", "discarded"],
        ["prepared"],  # never sent
        ["prepared", "discarded"],
    )

    assert application_outcomes(tracker, now=_at(10)) == {"passed": 2, "rejected": 1, "ghosted": 1, "withdrawn": 1, "pending": 1}


def test_an_application_ghosted_then_invited_passed_the_application_stage():
    from door.core.jobs.tracker import application_outcomes

    tracker = _ledger(["applied", "ghosted", "interview:screening"])

    assert application_outcomes(tracker, now=_at(10))["passed"] == 1


def test_an_application_with_no_change_for_45_days_counts_as_ghosted():
    from datetime import timedelta

    from door.core.jobs.tracker import application_outcomes, standings

    tracker = _ledger(["applied"], ["applied", "interview:screening"], ["prepared"])
    applied_at = _at(1)

    assert application_outcomes(tracker, now=applied_at + timedelta(days=45))["pending"] == 1
    assert standings(tracker, now=applied_at + timedelta(days=45))["waiting"] == 1
    later = applied_at + timedelta(days=46)
    assert application_outcomes(tracker, now=later) == {"passed": 1, "rejected": 0, "ghosted": 1, "withdrawn": 0, "pending": 0}
    # only the silent application: an interview round stays an interview, an unsent job is not counted
    assert standings(tracker, now=later) == {
        "offer": 0, "interviewing": 1, "waiting": 0, "rejected": 0, "ghosted": 1, "withdrawn": 0}


def test_no_answer_is_an_applied_or_interview_card_silent_for_more_than_45_days():
    from datetime import timedelta

    from door.core.jobs.tracker import NO_ANSWER_DAYS, no_answer

    tracker = _ledger(["applied"], ["applied", "interview:screening"], ["prepared"], ["applied", "offer"],
                      ["applied", "rejected"], ["applied", "ghosted"], ["applied", "discarded"])
    later = _at(1) + timedelta(days=NO_ANSWER_DAYS + 10)

    assert no_answer(tracker, "job-0", later) is True
    assert no_answer(tracker, "job-1", later + timedelta(days=1)) is True
    for n in (2, 3, 4, 5, 6):
        assert no_answer(tracker, f"job-{n}", later + timedelta(days=5)) is False, n


def test_no_answer_waits_for_more_than_45_days_and_reads_the_last_event():
    from datetime import timedelta

    from door.core.jobs.tracker import no_answer

    tracker = _ledger(["applied"])
    assert no_answer(tracker, "job-0", _at(1) + timedelta(days=45)) is False
    assert no_answer(tracker, "job-0", _at(1) + timedelta(days=46)) is True


def test_no_answer_is_false_for_an_unknown_job_and_for_a_recent_one_on_the_default_clock():
    from door.core.jobs.tracker import no_answer

    tracker = _ledger()
    assert no_answer(tracker, "job-missing", _at(30)) is False
    tracker.set_status("job-new", "applied")
    assert no_answer(tracker, "job-new") is False


def test_no_answer_count_counts_silent_applied_and_interview_jobs_only():
    from datetime import timedelta

    from door.core.jobs.tracker import NO_ANSWER_DAYS, no_answer_count

    tracker = _ledger(["applied"], ["applied", "interview:screening"], ["prepared"], ["applied", "offer"],
                      ["applied", "rejected"], ["applied", "ghosted"])
    later = _at(1) + timedelta(days=NO_ANSWER_DAYS + 10)

    assert no_answer_count(tracker, later) == 2
    assert no_answer_count(tracker, _at(3)) == 0
    assert no_answer_count(_ledger(), later) == 0


def test_the_pass_rate_counts_only_decided_rounds_with_a_one_sigma_binomial_interval():
    from door.core.jobs.tracker import pass_rate

    rate = pass_rate({"passed": 4, "rejected": 1, "ghosted": 1, "withdrawn": 3, "pending": 2})

    assert (rate["passed"], rate["decided"]) == (4, 6)
    assert rate["rate"] == pytest.approx(4 / 6)
    assert (rate["low"], rate["high"]) == (pytest.approx(0.4632, abs=1e-3), pytest.approx(0.8225, abs=1e-3))


def test_the_binomial_interval_stays_inside_zero_and_one_and_is_wide_on_one_round():
    from door.core.jobs.tracker import pass_rate

    assert pass_rate({"passed": 1, "rejected": 0, "ghosted": 0, "withdrawn": 0, "pending": 0}) == {
        "passed": 1, "decided": 1, "rate": 1.0, "low": pytest.approx(0.5), "high": 1.0,
    }
    nothing_passed = pass_rate({"passed": 0, "rejected": 2, "ghosted": 0, "withdrawn": 0, "pending": 0})
    assert (nothing_passed["rate"], nothing_passed["low"]) == (0.0, 0.0)


def test_no_pass_rate_until_a_round_is_decided():
    from door.core.jobs.tracker import pass_rate

    assert pass_rate({"passed": 0, "rejected": 0, "ghosted": 0, "withdrawn": 1, "pending": 2}) == {
        "passed": 0, "decided": 0, "rate": None, "low": None, "high": None,
    }


# --------------------------------------------------------------------------- #
# Capture for learning: the event's own date, the materials sent
# --------------------------------------------------------------------------- #

def test_at_dates_the_event_when_it_happened_and_keeps_when_it_was_logged(tmp_path):
    t = _tracker(tmp_path)
    t.set_status("job-1", "applied", now=_NOW, at=datetime(2026, 7, 1, tzinfo=timezone.utc))

    [event] = t.history("job-1")
    assert event["at"] == "2026-07-01T00:00:00+00:00"
    assert event["logged_at"] == _NOW.isoformat()


def test_an_event_without_at_has_no_logged_at(tmp_path):
    t = _tracker(tmp_path)
    t.set_status("job-1", "applied", now=_NOW)

    assert "logged_at" not in t.history("job-1")[0]


def test_a_backdated_event_goes_into_the_history_in_date_order(tmp_path):
    """Trustpilot's case: the screening was logged first, the application is backfilled after."""
    t = _tracker(tmp_path)
    t.set_status("job-1", "interview:screening", now=_NOW)
    t.set_status("job-1", "applied", now=_NOW, at=datetime(2026, 7, 1, tzinfo=timezone.utc), notes="via site")

    assert [e["status"] for e in t.history("job-1")] == ["applied", "interview:screening"]
    assert t.get_status("job-1") == "interview:screening"
    assert t._data["job-1"]["updated_at"] == _NOW.isoformat()
    assert "notes" not in t._data["job-1"]  # the latest event's notes, not the backfilled one's


def test_a_naive_at_is_read_as_utc(tmp_path):
    t = _tracker(tmp_path)
    t.set_status("job-1", "applied", now=_NOW, at=datetime(2026, 7, 1, 9, 30))

    assert t.history("job-1")[0]["at"] == "2026-07-01T09:30:00+00:00"


def test_at_in_the_future_is_refused(tmp_path):
    t = _tracker(tmp_path)
    with pytest.raises(ValueError, match="future"):
        t.set_status("job-1", "applied", now=_NOW, at=datetime(2026, 7, 12, tzinfo=timezone.utc))


def test_parse_at_reads_a_date_or_a_datetime():
    from door.core.jobs.tracker import parse_at

    assert parse_at("2026-08-23") == datetime(2026, 8, 23, tzinfo=timezone.utc)
    assert parse_at("2026-08-23T14:05") == datetime(2026, 8, 23, 14, 5, tzinfo=timezone.utc)
    assert parse_at("2026-08-23T14:05:00+02:00").utcoffset().total_seconds() == 7200
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_at("last tuesday")


def test_the_materials_sent_are_kept_through_later_changes(tmp_path):
    t = _tracker(tmp_path)
    t.set_status("job-1", "applied", now=_NOW, materials={"cv.html": "abc"})
    t.set_status("job-1", "interview:screening", now=_NOW)
    t.save()

    assert ApplicationTracker(tmp_path / "applications.json").materials("job-1") == {"cv.html": "abc"}


def test_is_sent_covers_applied_and_everything_after_it():
    from door.core.jobs.tracker import is_sent

    assert all(is_sent(s) for s in ("applied", "interview:screening", "ghosted", "rejected", "offer"))
    assert not any(is_sent(s) for s in ("unapplied", "prepared", "discarded", None))


def test_application_results_name_how_each_sent_application_went():
    from datetime import timedelta

    from door.core.jobs.tracker import application_outcomes, application_results

    tracker = _ledger(["applied", "interview:screening"], ["applied"], ["prepared"], ["applied", "rejected"])
    later = _at(1) + timedelta(days=60)

    results = application_results(tracker, now=later)

    assert results == {"job-0": "passed", "job-1": "ghosted", "job-3": "rejected"}
    counts = application_outcomes(tracker, now=later)
    assert counts == {"passed": 1, "rejected": 1, "ghosted": 1, "withdrawn": 0, "pending": 0}


def _band_inputs(top, near):
    """results and scores for (score, result) pairs: top ones at 0.9, near ones at 0.6."""
    results, scores = {}, {}
    for n, result in enumerate(top):
        results[f"t{n}"], scores[f"t{n}"] = result, 0.9
    for n, result in enumerate(near):
        results[f"n{n}"], scores[f"n{n}"] = result, 0.6
    return results, scores


def test_score_bands_split_at_the_median_and_rate_each_band():
    from door.core.jobs.tracker import pass_rate, score_bands

    results, scores = _band_inputs(["passed"] * 5 + ["rejected"] * 1, ["passed"] * 1 + ["ghosted"] * 5)

    bands = score_bands(results, scores)

    assert bands["split"] == 0.9
    assert bands["top"] == pass_rate({"passed": 5, "rejected": 1})
    assert bands["near_min"] == pass_rate({"passed": 1, "ghosted": 5})
    assert bands["reading"] == "near_min_lower"


def test_score_bands_leave_out_jobs_with_no_score():
    from door.core.jobs.tracker import score_bands

    results, scores = _band_inputs(["passed"] * 5, ["rejected"] * 5)
    for n, bad in enumerate((None, 0, 0.0)):
        results[f"x{n}"] = "passed"
        if bad is not None:
            scores[f"x{n}"] = bad
    results["x9"] = "passed"  # no posting at all

    bands = score_bands(results, scores)

    assert (bands["top"]["decided"], bands["near_min"]["decided"]) == (5, 5)


def test_score_bands_need_five_decided_in_each_band():
    from door.core.jobs.tracker import score_bands

    results, scores = _band_inputs(["passed"] * 5, ["rejected"] * 4)
    assert score_bands(results, scores) is None
    results, scores = _band_inputs(["passed"] * 4, ["rejected"] * 5)
    assert score_bands(results, scores) is None


def test_score_bands_split_among_the_distinct_scores_as_evenly_as_possible():
    from door.core.jobs.tracker import score_bands

    results = {f"j{n}": "rejected" for n in range(7)} | {f"k{n}": "passed" for n in range(6)}
    scores = {f"j{n}": 0.7 for n in range(7)} | {f"k{n}": 0.9 for n in range(6)}

    bands = score_bands(results, scores)

    assert bands["split"] == 0.9
    assert (bands["top"]["decided"], bands["near_min"]["decided"]) == (6, 7)
    # 4 at 0.5, 1 at 0.6, 4 at 0.7: splitting at 0.6 or at 0.7 is as even; the higher one wins
    results = {f"j{n}": "passed" for n in range(9)}
    scores = {f"j{n}": (0.5, 0.5, 0.5, 0.5, 0.6, 0.7, 0.7, 0.7, 0.7)[n] for n in range(9)}
    assert score_bands(results, scores, min_decided=1)["split"] == 0.7


def test_score_bands_with_one_distinct_score_are_none():
    from door.core.jobs.tracker import score_bands

    results = {f"j{n}": "passed" for n in range(12)}
    assert score_bands(results, dict.fromkeys(results, 0.8)) is None


def test_score_bands_have_no_reading_when_the_ranges_overlap_or_the_top_is_lower():
    from door.core.jobs.tracker import score_bands

    results, scores = _band_inputs(["passed"] * 3 + ["rejected"] * 3, ["passed"] * 2 + ["rejected"] * 4)
    assert score_bands(results, scores)["reading"] is None
    results, scores = _band_inputs(["passed"] * 1 + ["ghosted"] * 5, ["passed"] * 5 + ["rejected"] * 1)
    bands = score_bands(results, scores)
    assert bands is not None and bands["reading"] is None


def test_score_bands_decide_only_passed_rejected_and_ghosted():
    from door.core.jobs.tracker import score_bands

    results, scores = _band_inputs(["passed"] * 5 + ["pending", "withdrawn"], ["rejected"] * 5 + ["pending"] * 2)

    bands = score_bands(results, scores)

    assert (bands["top"]["decided"], bands["near_min"]["decided"]) == (5, 5)
