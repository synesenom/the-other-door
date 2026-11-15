"""A review session (CLAUDE.md "Review sessions"), run by the real model on the local plan (#33).

Not a skill: the user just says "let's go through my jobs" in a repo whose CLAUDE.md the conversation loads.
Marker `skills`, never CI. Checks are on behaviour: it starts from the status, lists the matches before
showing any, ends with `mark_reviewed` once the user says they are done, and does nothing unasked.
"""

import json

import pytest

from conftest import home, run_skill

pytestmark = pytest.mark.skills

UNASKED = ("find_jobs", "prepare", "import_posting", "set_status", "revise")


@pytest.fixture(scope="module")
def review(tmp_path_factory):
    return run_skill(tmp_path_factory, "review", "Let's go through my jobs.", max_turns=8,
                     stop_after_tool="mark_reviewed", persona_kind="onboarded",
                     facts_note="You only want to look at what is new and then finish: do not ask for anything to be "
                                "run, prepared or changed, and when the assistant has shown you the jobs, say you are done.")


def test_it_starts_from_the_status_and_lists_the_matches_before_showing_one(review):
    _, result = review
    tools = result["tools"]
    assert tools[0] == "status_summary", tools
    assert "list_matches" in tools, tools
    if "show" in tools:
        assert tools.index("list_matches") < tools.index("show"), tools


def test_it_marks_the_review_done_once_and_last(review):
    world, result = review
    tools = result["tools"]
    assert tools.count("mark_reviewed") == 1 and tools[-1] == "mark_reviewed", tools
    stamp = json.loads((home(world) / "jobs" / "last_review.json").read_text(encoding="utf-8"))
    assert stamp.get("reviewed_at")


def test_it_runs_nothing_the_user_did_not_ask_for(review):
    _, result = review
    assert not [t for t in result["tools"] if t in UNASKED], result["tools"]
    assert not [u for u in result["used"] if u["tool"] in ("Bash", "Write", "Edit")], result["used"]
