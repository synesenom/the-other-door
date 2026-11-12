"""The five-line step display of `find` (restructure phase B): a pure function from state to lines,
the state machine that folds progress events into it, and the plain one-line-per-step renderer."""

import io
import json

import click
import pytest

from door.core.progress import Progress
from door.pipeline import display

PLAN = Progress("plan", stage="steps", detail="search,discover,follow,collect,match")


def step(name, outcome, detail=None, total=None):
    return Progress(detail or "started", 0 if outcome == "start" else None, total, site=name, stage="step",
                    outcome=outcome, detail=detail)


def board(*events, now=100.0):
    state = display.BoardState()
    for event in events:
        state.apply(event, now=now)
    return state


def lines(state, *, now=100.0, color=False, width=100):
    return [click.unstyle(l) for l in display.render_lines(state, frame="⠹", now=now, width=width, color=color)]


def test_the_plan_gives_five_waiting_lines():
    out = lines(board(PLAN))
    assert out == ["○ search", "○ discover", "○ follow", "○ collect", "○ match"]


def test_a_single_step_plan_has_one_line():
    out = lines(board(Progress("plan", stage="steps", detail="collect")))
    assert out == ["○ collect"]


def test_a_finished_step_shows_its_summary_and_elapsed_time():
    state = board(PLAN, step("search", "start", total=6))
    state.apply(step("search", "done", "41 postings from 2 boards"), now=112.0)
    assert lines(state, now=112.0)[0] == "✓ search    41 postings from 2 boards (12s)"


def test_elapsed_time_is_written_in_minutes_when_long():
    assert display.format_elapsed(12) == "12s"
    assert display.format_elapsed(252) == "4m12s"
    assert display.format_elapsed(41 * 60 + 5) == "41m"
    assert display.format_elapsed(3900) == "1h05m"


def test_a_failed_step_has_a_cross_and_the_reason():
    state = board(PLAN, step("follow", "start"))
    state.apply(step("follow", "failed", "ConfigError: bad"), now=101.0)
    assert lines(state, now=101.0)[2] == "✗ follow    ConfigError: bad (1s)"


def test_a_skipped_step_is_dashed_with_its_reason():
    state = board(PLAN, step("discover", "skipped", "LinkedIn resting until 14:20"))
    assert lines(state)[1] == "– discover  skipped: LinkedIn resting until 14:20"


def test_partial_failure_stays_done_and_colours_the_failed_count_yellow():
    state = board(PLAN, step("collect", "start"))
    state.apply(step("collect", "done", "158 employers, 2,431 postings, 2 failed"), now=2500.0)
    raw = display.render_lines(state, frame="⠹", now=2500.0, width=100, color=True)[3]
    assert click.unstyle(raw) == "✓ collect   158 employers, 2,431 postings, 2 failed (40m)"
    assert click.style("2 failed", fg="yellow") in raw and raw.startswith(click.style("✓", fg="green"))


def test_colours_waiting_grey_running_yellow_failed_red_skipped_grey():
    state = board(PLAN, step("search", "start"), step("discover", "skipped", "--skip"), step("follow", "failed", "x"))
    raw = display.render_lines(state, frame="⠹", now=100.0, width=100, color=True)
    assert raw[0].startswith(click.style("⠹", fg="yellow"))
    assert raw[1].startswith(click.style("–", fg="bright_black"))
    assert raw[2].startswith(click.style("✗", fg="red"))
    assert raw[3].startswith(click.style("○", fg="bright_black"))


def _boards(state, *pairs):
    state.apply(Progress("items", site="search", stage="items", detail=json.dumps([list(p) for p in pairs])), now=100.0)


def test_search_counts_the_boards_it_finished_and_postings_per_board():
    state = board(PLAN, step("search", "start"))
    _boards(state, ("jobindex", "Jobindex"), ("thehub", "The Hub"), ("reed", "Reed"), ("euraxess", "EURAXESS"))
    state.apply(Progress("jobindex", site="jobindex", stage="scrape"), now=100.0)
    state.apply(Progress("jobindex", site="jobindex", stage="scrape", outcome="ok"), now=100.0)
    state.apply(Progress("thehub", site="thehub", stage="scrape", outcome="failed"), now=100.0)
    state.apply(Progress("postings", 41, site="jobindex", stage="postings"), now=100.0)
    state.apply(Progress("postings", 12, site="reed", stage="postings"), now=100.0)
    assert lines(state)[0] == "⠹ search    █████░░░░░  2/4 boards · jobindex 41, reed 12"


def test_a_running_board_says_which_keyword_it_searches_then_which_ad_it_reads():
    state = board(PLAN, step("search", "start"))
    _boards(state, ("jobindex", "Jobindex"), ("thehub", "The Hub"))
    state.apply(Progress("jobindex", site="jobindex", stage="scrape"), now=100.0)
    state.apply(Progress("data", 3, 21, site="jobindex", stage="keyword_search"), now=100.0)
    jobindex = state.steps["search"].items[0]
    assert jobindex.activity == {"kind": "searching", "keyword": "data", "done": 3, "total": 21}
    state.apply(Progress("data", 12, 40, site="jobindex", stage="ad_details"), now=100.0)
    assert jobindex.activity == {"kind": "reading", "keyword": "data", "done": 12, "total": 40}
    assert lines(state, width=200)[0] == "⠹ search    ░░░░░░░░░░  0/2 boards · jobindex: reading ads for 'data' (12 of 40)"
    # a board that finished has nothing in progress
    state.apply(Progress("jobindex", site="jobindex", stage="scrape", outcome="ok"), now=100.0)
    assert jobindex.activity is None
    assert lines(state)[0] == "⠹ search    █████░░░░░  1/2 boards"


def test_a_board_not_read_at_all_leaves_the_count():
    state = board(PLAN, step("search", "start"))
    _boards(state, ("jobindex", "Jobindex"), ("jobbank", "Akademikernes Jobbank"))
    state.apply(Progress("jobbank", site="jobbank", stage="scrape", outcome="resting"), now=100.0)
    state.apply(Progress("jobindex", site="jobindex", stage="scrape", outcome="ok"), now=100.0)
    assert lines(state)[0] == "⠹ search    ██████████  1/1 boards"


def test_a_running_step_without_a_known_total_has_no_bar():
    state = board(PLAN, step("follow", "start"))
    state.apply(Progress("c", 1, None, stage="candidate"), now=100.0)
    assert lines(state)[2] == "⠹ follow    1 candidates"


def li(message, done, total=None, stage="li_request"):
    return Progress(message, done, total, site="linkedin", stage=stage)


def test_discover_shows_the_request_it_is_on_out_of_its_budget():
    state = board(PLAN, step("discover", "start", total=15))
    assert lines(state)[1] == "⠹ discover  ░░░░░░░░░░"
    state.apply(li("page 3/15", 3, 15), now=100.0)
    assert lines(state)[1] == "⠹ discover  ██░░░░░░░░  page 3/15"
    state.apply(li("job page 12/15", 12, 15), now=100.0)
    assert lines(state)[1] == "⠹ discover  ████████░░  job page 12/15"


def test_discover_counts_down_the_pause_between_requests():
    state = board(PLAN, step("discover", "start", total=15), now=100.0)
    state.apply(li("page 3/15", 3, 15), now=100.0)
    state.apply(li("waiting 87 s", 87, stage="li_wait"), now=100.0)
    assert lines(state, now=100.0)[1] == "⠹ discover  ██░░░░░░░░  page 3/15 · waiting 87 s"
    assert lines(state, now=130.0)[1].endswith("page 3/15 · waiting 57 s")
    assert lines(state, now=190.0)[1].endswith("page 3/15")  # the pause is over: the request is on its way


def test_discover_is_done_when_its_requests_end_and_its_summary_comes_when_it_is_queued():
    state = board(PLAN, step("discover", "start", total=150), now=100.0)
    state.apply(li("page 85/150", 85, 150), now=100.0)
    state.apply(li("waiting 3 s", 3, stage="li_wait"), now=100.0)
    end = Progress("85/150 requests, stopped: HTTP 429; queuing at the next step", 85, 150, site="linkedin",
                   stage="li_end", outcome="done")
    state.apply(end, now=130.0)
    assert lines(state, now=131.0)[1] == "✓ discover  85/150 requests, stopped: HTTP 429; queuing at the next step (30s)"
    state.apply(step("discover", "done", "12 employers, 9 queued"), now=900.0)
    assert lines(state, now=900.0)[1] == "✓ discover  12 employers, 9 queued (30s)"  # LinkedIn's time, not the wait


def test_li_end_from_any_discovery_source_ends_the_discover_line():
    state = board(PLAN, step("discover", "start", total=150), now=100.0)
    state.apply(Progress("12/150 requests, search complete; queuing at the next step", 12, 150, site="fake",
                         stage="li_end", outcome="done"), now=110.0)
    assert lines(state, now=111.0)[1].startswith("✓ discover  12/150 requests")


def test_a_discover_thread_that_crashed_is_failed_at_once():
    state = board(PLAN, step("discover", "start", total=150), now=100.0)
    state.apply(Progress("failed: RuntimeError: boom", site="linkedin", stage="li_end", outcome="failed"), now=105.0)
    assert lines(state, now=106.0)[1] == "✗ discover  failed: RuntimeError: boom (5s)"


def test_discover_keeps_spinning_while_the_other_steps_run_and_each_line_gets_its_own_events():
    state = board(PLAN, step("discover", "start", total=15), step("search", "start", total=6))
    state.apply(step("search", "done", "41 postings from 2 boards"), now=110.0)
    state.apply(step("follow", "start", total=40), now=110.0)
    state.apply(li("page 2/15", 2, 15), now=111.0)
    state.apply(Progress("checking", 12, 40, stage="candidate"), now=111.0)
    state.apply(Progress("'x': 2 results", site="jobindex", stage="keyword"), now=111.0)
    out = lines(state, now=112.0)
    assert out[1] == "⠹ discover  █░░░░░░░░░  page 2/15"
    assert out[2] == "⠹ follow    ███░░░░░░░  12/40 candidates"


def test_discover_ending_while_another_step_runs_leaves_that_step_running():
    state = board(PLAN, step("discover", "start", total=15), step("collect", "start", total=9))
    state.apply(step("discover", "done", "12 employers, 9 queued"), now=130.0)
    state.apply(Progress("postings", 5, site="lever", stage="postings"), now=130.0)
    out = lines(state, now=130.0)
    assert out[1] == "✓ discover  12 employers, 9 queued (30s)" and "5 postings" in out[3]


def test_a_late_follow_is_folded_into_the_follow_line():
    state = board(PLAN, step("follow", "start", total=40))
    state.apply(step("follow", "done", "40 candidates: 5 followed, 20 unfollowable, 15 unresolved"), now=140.0)
    state.apply(Progress("started", 0, 3, site="follow", stage="late", outcome="start"), now=150.0)
    state.apply(Progress("checking", 1, 3, stage="candidate"), now=151.0)
    assert lines(state, now=152.0)[2] == "⠹ follow    ███░░░░░░░  late 1/3 candidates"
    state.apply(Progress("3 candidates: 2 followed, 0 unfollowable, 1 unresolved", site="follow", stage="late",
                         outcome="done", detail="3 candidates: 2 followed, 0 unfollowable, 1 unresolved"), now=160.0)
    assert lines(state, now=160.0, width=200)[2] == ("✓ follow    40 candidates: 5 followed, 20 unfollowable, 15 unresolved"
                                          " + late: 3 candidates: 2 followed, 0 unfollowable, 1 unresolved (1m00s)")


def test_a_late_collect_is_folded_into_the_collect_line_and_a_failed_one_is_a_note():
    state = board(PLAN, step("collect", "start", total=9))
    state.apply(step("collect", "done", "9 employers, 100 postings"), now=140.0)
    state.apply(Progress("started", 0, 2, site="collect", stage="late", outcome="start"), now=150.0)
    state.apply(Progress("lever", stage="entry_start"), now=150.0)
    assert lines(state, now=151.0)[3] == "⠹ collect   ░░░░░░░░░░  late 0/2 employers · 0 postings · lever"
    state.apply(Progress("boom", site="collect", stage="late", outcome="failed", detail="boom"), now=160.0)
    assert lines(state, now=160.0)[3].startswith("✓ collect   9 employers, 100 postings + late failed: boom")


def test_follow_counts_candidates_checked():
    state = board(PLAN, step("follow", "start", total=40))
    state.apply(Progress("checking", 12, 40, stage="candidate"), now=100.0)
    assert lines(state)[2] == "⠹ follow    ███░░░░░░░  12/40 candidates"


def test_collect_shows_employers_done_postings_and_up_to_three_hosts_in_flight():
    state = board(PLAN, step("collect", "start", total=158))
    for host in ("a.com", "b.com", "c.com", "d.com"):
        state.apply(Progress(host, stage="entry_start"), now=100.0)
    state.apply(Progress("a.com", stage="entry_end"), now=100.0)
    state.apply(Progress("postings", 1204, site="greenhouse", stage="postings"), now=100.0)
    state.apply(Progress("postings", 30, site="lever", stage="postings"), now=100.0)
    assert lines(state)[3] == "⠹ collect   ░░░░░░░░░░  1/158 employers · 1,234 postings · b.com, c.com, d.com"


def test_collect_lists_at_most_three_hosts():
    state = board(PLAN, step("collect", "start", total=9))
    for host in ("a", "b", "c", "d", "e"):
        state.apply(Progress(host, stage="entry_start"), now=100.0)
    assert lines(state)[3].endswith("a, b, c")


def test_a_host_in_flight_twice_ends_once_per_end_event():
    state = board(PLAN, step("collect", "start", total=9))
    state.apply(Progress("a", stage="entry_start"), now=100.0)
    state.apply(Progress("a", stage="entry_start"), now=100.0)
    state.apply(Progress("a", stage="entry_end"), now=100.0)
    assert lines(state)[3].endswith("a")


def test_match_counts_postings_scored_and_names_the_pass_before_scoring():
    state = board(PLAN, step("match", "start"))
    state.apply(Progress("pre-filter", stage="prefilter"), now=100.0)
    assert lines(state)[4] == "⠹ match     pre-filter"
    state.apply(Progress("scoring", 0, 300, stage="match"), now=100.0)
    state.apply(Progress("scored", 120, 300, stage="match"), now=100.0)
    assert lines(state)[4] == "⠹ match     ████░░░░░░  120/300 scored"


def test_events_before_any_step_starts_are_ignored():
    state = board(PLAN, Progress("'x': 2 results", site="jobindex", stage="keyword"))
    assert lines(state) == ["○ search", "○ discover", "○ follow", "○ collect", "○ match"]


def test_a_new_step_forgets_the_counters_of_the_last_one():
    state = board(PLAN, step("search", "start", total=2))
    state.apply(Progress("'x': 2 results", site="jobindex", stage="keyword"), now=100.0)
    state.apply(step("search", "done", "1 postings"), now=100.0)
    state.apply(step("follow", "start", total=5), now=100.0)
    assert lines(state)[2] == "⠹ follow    ░░░░░░░░░░  0/5 candidates"


def test_long_lines_are_cut_to_the_width():
    state = board(PLAN, step("collect", "start", total=9))
    for host in ("a-very-long-host-name.example.com",) * 3:
        state.apply(Progress(host, stage="entry_start"), now=100.0)
    out = lines(state, width=40)
    assert all(len(l) <= 40 for l in out) and out[3].endswith("…")


def test_the_full_board_sample():
    """What the user sees mid-run: two steps done, one running, one waiting, one skipped."""
    state = board(PLAN, step("search", "start", total=6))
    state.apply(step("search", "done", "41 postings from 2 boards"), now=112.0)
    state.apply(step("discover", "skipped", "LinkedIn resting until 14:20"), now=112.0)
    state.apply(step("follow", "start", total=40), now=112.0)
    state.apply(step("follow", "done", "40 candidates: 5 followed, 20 unfollowable, 15 unresolved"), now=300.0)
    state.apply(step("collect", "start", total=158), now=300.0)
    for host in ("jobs.lego.com", "careers.novo.com"):
        state.apply(Progress(host, stage="entry_start"), now=300.0)
    state.apply(Progress("postings", 640, site="greenhouse", stage="postings"), now=300.0)
    out = lines(state, now=400.0, width=120)
    print("\n".join(out))
    assert out == [
        "✓ search    41 postings from 2 boards (12s)",
        "– discover  skipped: LinkedIn resting until 14:20",
        "✓ follow    40 candidates: 5 followed, 20 unfollowable, 15 unresolved (3m08s)",
        "⠹ collect   ░░░░░░░░░░  0/158 employers · 640 postings · jobs.lego.com, careers.novo.com",
        "○ match",
    ]


# --------------------------------------------------------------------------- #
# the plain renderer: one line per step as it finishes
# --------------------------------------------------------------------------- #

def plain(*events, clock=None):
    out = io.StringIO()
    reporter = display.PlainSteps(out, clock=clock or iter([0.0, 2460.0, 2460.0]).__next__)
    for e in events:
        reporter.report(e)
    return out.getvalue().splitlines()


def test_plain_prints_one_numbered_line_per_finished_step():
    assert plain(PLAN, step("collect", "start"), step("collect", "done", "158 employers, 2,431 postings, 2 failed")) == [
        "[4/5] collect: 158 employers, 2,431 postings, 2 failed (41m)"
    ]


def test_plain_prints_skipped_and_failed_steps():
    got = plain(PLAN, step("discover", "skipped", "--skip"), step("follow", "start"), step("follow", "failed", "boom"),
                clock=iter([0.0, 3.0]).__next__)
    assert got == ["[2/5] discover: skipped (--skip)", "[3/5] follow: failed - boom (3s)"]


def test_plain_ignores_everything_but_step_ends():
    assert plain(PLAN, Progress("'x': 1 results", site="jobindex", stage="keyword"), step("search", "start")) == []


def test_a_single_step_is_numbered_one_of_one():
    got = plain(Progress("plan", stage="steps", detail="match"), step("match", "start"), step("match", "done", "12 scored"),
                clock=iter([0.0, 5.0]).__next__)
    assert got == ["[1/1] match: 12 scored (5s)"]


# --------------------------------------------------------------------------- #
# the live board on a stream
# --------------------------------------------------------------------------- #

def test_the_live_board_redraws_its_lines_in_place():
    out = io.StringIO()
    live = display.StepBoard(out, animate=False, clock=lambda: 100.0)
    live.report(PLAN)
    first = out.getvalue()
    assert click.unstyle(first).count("\n") == 5 and "\033[5A" not in first
    live.report(step("search", "start", total=2))
    assert "\033[5A" in out.getvalue()          # cursor back up over the five lines
    live.stop()
    assert "○ discover" in click.unstyle(out.getvalue())


def test_plain_prints_a_line_for_a_late_pass_too():
    out = plain(PLAN, step("follow", "start"), step("follow", "done", "3 candidates"),
                Progress("2 candidates: 1 followed", site="follow", stage="late", outcome="done",
                         detail="2 candidates: 1 followed"))
    assert out[-1] == "[3/5] follow (late): 2 candidates: 1 followed"


# -- the boards and sources a step reads (the app lists them under the step's bar) ------------------

def items(name, *pairs):
    return Progress("items", site=name, stage="items", detail=json.dumps([list(p) for p in pairs]))


def scraped(site, outcome=None):
    return Progress(site, site=site, stage="scrape", outcome=outcome)


def item(name, source, outcome):
    return Progress(source, site=name, stage="item", outcome=outcome, detail=source)


def test_a_step_lists_its_boards_waiting_then_reads_and_checks_each():
    state = board(PLAN, step("search", "start", total=6),
                  items("search", ("jobindex", "Jobindex"), ("thehub", "The Hub"), ("euraxess", "EURAXESS")))
    assert [(i.label, i.state) for i in state.steps["search"].items] == [
        ("Jobindex", "waiting"), ("The Hub", "waiting"), ("EURAXESS", "waiting")]
    for event in (scraped("jobindex"), scraped("thehub"), scraped("thehub", "ok"), scraped("euraxess"),
                  scraped("euraxess", "failed")):
        state.apply(event, now=101.0)
    assert [(i.label, i.state) for i in state.steps["search"].items] == [
        ("Jobindex", "running"), ("The Hub", "done"), ("EURAXESS", "failed")]


def test_a_board_that_is_not_read_leaves_the_list_and_an_empty_one_is_checked():
    state = board(PLAN, step("search", "start"), items("search", ("jobindex", "Jobindex"), ("jobbank", "Jobbank")))
    state.apply(scraped("jobbank", "resting"), now=101.0)
    state.apply(scraped("jobindex", "empty"), now=101.0)
    assert [(i.label, i.state) for i in state.steps["search"].items] == [("Jobindex", "done")]


def test_a_collect_feed_is_not_listed_and_a_new_start_clears_the_list():
    state = board(PLAN, step("collect", "start", total=3))
    state.apply(scraped("greenhouse"), now=101.0)
    assert state.steps["collect"].items == []
    state = board(PLAN, step("search", "start"), items("search", ("jobindex", "Jobindex")), step("search", "start"))
    assert state.steps["search"].items == []


def test_discover_lists_its_sources_while_search_runs_in_front():
    state = board(PLAN, step("discover", "start", total=150), step("search", "start", total=6),
                  items("discover", ("linkedin", "LinkedIn"), ("profession", "profession.hu")),
                  item("discover", "linkedin", "start"))
    state.apply(scraped("linkedin"), now=101.0)  # a board's event never touches discover's list
    state.apply(item("discover", "linkedin", "done"), now=102.0)
    state.apply(item("discover", "profession", "start"), now=102.0)
    assert [(i.label, i.state) for i in state.steps["discover"].items] == [("LinkedIn", "done"), ("profession.hu", "running")]
    state.apply(item("discover", "profession", "failed"), now=103.0)
    assert state.steps["discover"].items[1].state == "failed"
