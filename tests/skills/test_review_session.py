"""A review session (CLAUDE.md "Review sessions"), run by the real model on the local plan (#33).

Not a skill: the user just says "let's go through my jobs" in a repo whose CLAUDE.md the conversation loads.
Marker `skills`, never CI. Checks are on behaviour: it starts from the status, lists the matches before
showing any, ends with `mark_reviewed` once the user says they are done, and does nothing unasked; an
application with no answer for weeks is listed but not marked ghosted unasked. A second run acts on what
the user says (#103): "not this one", "prepare it" and "I applied".
"""

import json
from datetime import datetime, timedelta

import pytest

from conftest import home, run_skill

pytestmark = pytest.mark.skills

UNASKED = ("find_jobs", "prepare", "import_posting", "set_status", "revise")
NOW = datetime(2026, 10, 26, 9)   # the world's clock (`NOW` in app/test/world/build.ts)
SILENT = "lever.sundline-network-optimisation"   # applied; aged past tracker.NO_ANSWER_DAYS before the run
DISCARD, PREPARE, APPLIED = "lever.gridwise-ml-engineer-remote", "lever.baltic-power-lead-ds", "thehub.kronvej-ml-engineer-mlops"


def _age(world, job_id: str, days: int = 50) -> None:
    """Move every event of `job_id` in the ledger `days` back: the application has had no answer since."""
    path = home(world) / "jobs" / "applications.json"
    ledger = json.loads(path.read_text(encoding="utf-8"))
    at = (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    entry = ledger[job_id]
    entry["updated_at"] = at
    for event in entry["history"]:
        event["at"] = at
    path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")


@pytest.fixture(scope="module")
def review(tmp_path_factory):
    return run_skill(tmp_path_factory, "review", "Let's go through my jobs.", max_turns=8,
                     seed=lambda world: _age(world, SILENT),
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


def test_it_names_the_application_with_no_answer_but_does_not_mark_it_unasked(review):
    _, result = review
    ongoing = [c for c in result["calls"] if c["tool"] == "list_matches" and c["args"].get("ongoing")]
    assert ongoing, result["calls"]
    assert "set_status" not in result["tools"], result["tools"]


@pytest.fixture(scope="module")
def actions(tmp_path_factory):
    return run_skill(tmp_path_factory, "review-actions", "Let's go through my jobs.", max_turns=14,
                     stop_after_tool="mark_reviewed", persona_kind="onboarded",
                     facts_note="Once the assistant has shown you the jobs, do three things, one per message: say the "
                                "Gridwise Labs one is not for you because you do not want a fully remote job; ask for "
                                "the Baltic Power Trading one to be prepared; and say you applied to the Kronvej one "
                                "yesterday. Then say you are done.")


def _calls(result, tool):
    return [c for c in result["calls"] if c["tool"] == tool]


def _status(result, status):
    return [c for c in _calls(result, "set_status") if c["args"].get("status") == status]


def _names(call, job_id: str, *words: str) -> bool:
    """Whether a call's `job_id` is the job: its id, or words from its company."""
    given = str(call["args"].get("job_id", "")).lower()
    return given == job_id or any(w in given for w in words)


def test_not_this_one_discards_it_with_the_users_reason(actions):
    world, result = actions
    discarded = _status(result, "discarded")
    assert discarded and _names(discarded[0], DISCARD, "gridwise"), result["calls"]
    assert (discarded[0]["args"].get("notes") or "").strip(), discarded[0]
    ledger = json.loads((home(world) / "jobs" / "applications.json").read_text(encoding="utf-8"))
    assert ledger[DISCARD]["status"] == "discarded"


def test_prepare_it_prepares_then_shows_the_materials(actions):
    world, result = actions
    tools = result["tools"]
    prepares = _calls(result, "prepare")
    assert prepares and _names(prepares[0], PREPARE, "baltic"), result["calls"]
    assert "show" in tools[tools.index("prepare"):], tools
    assert (home(world) / "jobs" / "output" / PREPARE / "cv.pdf").exists()


def test_applied_records_it_for_the_job_the_user_named(actions):
    world, result = actions
    applied = _status(result, "applied")
    assert applied and _names(applied[0], APPLIED, "kronvej"), result["calls"]
    ledger = json.loads((home(world) / "jobs" / "applications.json").read_text(encoding="utf-8"))
    assert ledger[APPLIED]["status"] == "applied"


def test_acting_on_jobs_runs_no_search_and_no_shell(actions):
    _, result = actions
    assert "find_jobs" not in result["tools"], result["tools"]
    assert not [u for u in result["used"] if u["tool"] in ("Bash", "Write", "Edit")], result["used"]
