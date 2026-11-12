"""The step events every pipeline step reports (`door.pipeline`)."""

import pytest

from door import pipeline
from door.core.progress import Progress


def test_the_steps_run_in_this_order():
    assert pipeline.STEPS == ("search", "discover", "follow", "collect", "match")


def test_a_step_reports_start_then_done_with_its_summary(progress_events):
    with pipeline.running("collect", total=158) as step:
        step.summary = "158 employers, 2,431 postings"
    assert progress_events == [
        Progress("started", 0, 158, site="collect", stage="step", outcome="start"),
        Progress("158 employers, 2,431 postings", site="collect", stage="step", outcome="done",
                 detail="158 employers, 2,431 postings"),
    ]


def test_a_step_that_raises_reports_failed_and_lets_the_error_through(progress_events):
    with pytest.raises(ValueError):
        with pipeline.running("follow"):
            raise ValueError("boom")
    last = progress_events[-1]
    assert (last.site, last.outcome, last.detail) == ("follow", "failed", "ValueError: boom")


def test_a_step_can_report_itself_skipped(progress_events):
    pipeline.skipped("discover", "LinkedIn resting until 14:20")
    assert progress_events == [Progress("skipped: LinkedIn resting until 14:20", site="discover", stage="step",
                                        outcome="skipped", detail="LinkedIn resting until 14:20")]


def test_the_plan_lists_the_steps_about_to_run(progress_events):
    pipeline.plan(["search", "match"])
    assert progress_events == [Progress("plan", stage="steps", detail="search,match")]


def test_a_failed_step_can_be_marked_by_the_step_itself(progress_events):
    with pipeline.running("search") as step:
        step.fail("every board failed")
    assert progress_events[-1].outcome == "failed" and progress_events[-1].detail == "every board failed"


def test_elapsed_time_is_measured():
    ticks = iter([10.0, 14.5])
    with pipeline.running("match", clock=lambda: next(ticks)) as step:
        pass
    assert step.elapsed_s == 4.5


def test_a_late_pass_reports_late_events_not_step_events(progress_events):
    with pipeline.running("follow", total=2, late=True) as step:
        step.summary = "2 candidates: 1 followed"
    assert progress_events == [
        Progress("started", 0, 2, site="follow", stage="late", outcome="start"),
        Progress("2 candidates: 1 followed", site="follow", stage="late", outcome="done", detail="2 candidates: 1 followed"),
    ]


def test_a_step_started_and_finished_by_hand_reports_the_same_events(progress_events):
    pipeline.started("discover", 15)
    pipeline.finished("discover", "3 employers")
    pipeline.finished("discover", "x", "boom")
    assert [(e.outcome, e.total, e.detail) for e in progress_events] == [
        ("start", 15, None), ("done", None, "3 employers"), ("failed", None, "boom")]
