"""BoardState folds progress events into the view of find's steps."""

from __future__ import annotations

import json

from door.core.board_state import BoardState
from door.core.progress import Progress

PLAN = Progress("plan", stage="steps", detail="search,discover,follow,collect,match")


def step(name, outcome, detail=None, total=None):
    return Progress(detail or "started", 0 if outcome == "start" else None, total, site=name, stage="step",
                    outcome=outcome, detail=detail)


def board(*events, now=100.0):
    state = BoardState()
    for event in events:
        state.apply(event, now=now)
    return state


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
