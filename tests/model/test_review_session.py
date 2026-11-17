"""A review session (CLAUDE.md "Review sessions"), run by the real model on the local plan (#33).

Not a skill: the user just says "let's go through my jobs" in a repo whose CLAUDE.md the conversation loads.
Marker `skills`, never CI. Checks are on behaviour: it starts from the status, lists the matches before
showing any, ends with `mark_reviewed` once the user says they are done, and does nothing unasked; an
application with no answer for weeks is listed but not marked ghosted unasked. A second run acts on what
the user says (#103): "not this one", "prepare it" and "I applied". The CV style pick (#223): a style built from
the user's CV waiting (`status_summary.style` ready) is shown before it is chosen, both styles are offered with
neither recommended, the prepared CVs are printed again only on a yes and never after "keep my current style", and
a build still running or failed is not mentioned.
"""

import json
import re
import shutil
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone

import pytest

from door.core import lock, templates, tracker
from paths import REPO_ROOT

from conftest import home, run_skill

pytestmark = pytest.mark.model

UNASKED = ("find_jobs", "prepare", "import_posting", "set_status", "revise")
NOW = datetime(2026, 10, 26, 9, tzinfo=timezone.utc)   # the world's clock (`NOW` in app/test/world/build.ts)
SILENT = "lever.sundline-network-optimisation"   # applied; aged past tracker.NO_ANSWER_DAYS before the run
DISCARD, PREPARE, APPLIED = "lever.gridwise-ml-engineer-remote", "lever.baltic-power-lead-ds", "thehub.kronvej-ml-engineer-mlops"


def _age(world, job_id: str, days: int = tracker.NO_ANSWER_DAYS + 5) -> None:
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


def test_an_application_with_no_answer_is_looked_up_and_left_as_it_is(review):
    world, result = review
    ledger = tracker.ApplicationTracker(home(world) / "jobs" / "applications.json")
    assert tracker.no_answer(ledger, SILENT, NOW), "the seed did not age the application"
    ongoing = [c for c in result["calls"] if c["tool"] == "list_matches" and c["args"].get("ongoing")]
    assert ongoing, result["calls"]
    assert ledger.get_status(SILENT) == "applied"


ACTIONS = ("Let's go through my jobs. The Gridwise Labs one is not for me: I don't want a fully remote job. "
           "Please prepare the Baltic Power Trading one. And I applied to the Kronvej one.")


@pytest.fixture(scope="module")
def actions(tmp_path_factory):
    # the stand-in user sees only the assistant's last message, so the three asks come in the opening one;
    # "applied" carries no day: the model's own date is not the world's clock (NOW)
    return run_skill(tmp_path_factory, "review-actions", ACTIONS, max_turns=6, stop_after_tool="mark_reviewed",
                     persona_kind="onboarded",
                     facts_note="You have said everything you wanted in your first message. When the assistant has "
                                "done it or asks whether there is anything else, say you are done.")


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
    assert "remote" in (discarded[0]["args"].get("notes") or "").lower(), discarded[0]
    ledger = json.loads((home(world) / "jobs" / "applications.json").read_text(encoding="utf-8"))
    assert ledger[DISCARD]["status"] == "discarded"


def test_prepare_it_prepares_the_job_the_user_named(actions):
    # whether it then calls `show` or summarises from `prepare`'s own `materials` is the model's choice
    world, result = actions
    prepares = _calls(result, "prepare")
    assert prepares and _names(prepares[0], PREPARE, "baltic"), result["calls"]
    assert (home(world) / "jobs" / "output" / PREPARE / "cv.pdf").exists()


def test_applied_records_it_for_the_job_the_user_named(actions):
    world, result = actions
    applied = _status(result, "applied")
    assert applied and _names(applied[0], APPLIED, "kronvej"), result["calls"]
    ledger = json.loads((home(world) / "jobs" / "applications.json").read_text(encoding="utf-8"))
    assert ledger[APPLIED]["status"] == "applied"


def test_acting_on_jobs_runs_no_search_and_no_shell_and_ends_the_review(actions):
    _, result = actions
    assert result["tools"][-1] == "mark_reviewed", result["tools"]
    assert "find_jobs" not in result["tools"], result["tools"]
    assert not [u for u in result["used"] if u["tool"] in ("Bash", "Write", "Edit")], result["used"]


# ----------------------------------------------------------------------------- the CV style pick (#223)
IN_USE = "\n<!-- the style in use -->\n"


def _style_folder(world, folder: str) -> None:
    """A built style in `profile/<folder>/`: the default's own two templates stand in for one (the world's print lays
    out text only, so the look is never seen)."""
    target = home(world) / "profile" / folder
    target.mkdir(parents=True, exist_ok=True)
    for name in templates.FILES.values():
        shutil.copyfile(REPO_ROOT / "profile.example" / name, target / name)


def _run_record(world, state: str, **fields) -> None:
    path = home(world) / ".style" / "run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"state": state, "started_at": NOW.isoformat(timespec="seconds"), **fields}),
                    encoding="utf-8")


def _ready(world) -> None:
    """A style built from the user's CV waits to be compared; nothing in use changed."""
    _style_folder(world, "style.next")
    _run_record(world, "ready", pid=1, result={"state": "ready", "fonts": [], "dropped_icons": []})


def _ready_with_one_in_use(world) -> None:
    """An earlier style built from the user's CV is in use, and a newer one waits."""
    _style_folder(world, "style")
    with (home(world) / "profile" / "style" / templates.FILES["cv_template"]).open("a", encoding="utf-8") as f:
        f.write(IN_USE)   # tells the style in use from the waiting one
    config_path = home(world) / "profile" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.update(cv_template="profile/style/cv.template.html",
                  cover_letter_template="profile/style/cover-letter.template.html")
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    _ready(world)


STYLE_NOTE = "When the assistant has shown you the jobs, say you are done; ask for nothing to be run or prepared. "


def _review(tmp_path_factory, name: str, seed, wish: str = ""):
    """A review session in a world `seed` changed, the user wishing `STYLE_NOTE` and `wish`."""
    return run_skill(tmp_path_factory, name, "Let's go through my jobs.", max_turns=8, seed=seed,
                     stop_after_tool="mark_reviewed", persona_kind="onboarded", facts_note=STYLE_NOTE + wish)


@pytest.fixture(scope="module")
def style_like(tmp_path_factory):
    return _review(tmp_path_factory, "review-style-like", _ready,
                   "If the assistant asks which CV style to use, you want the style of your own CV: pick \"Use the "
                   "style of my CV\" (or the option that says the same), never The other door's. If it offers to print "
                   "your prepared applications again, say no, not now.")


@pytest.fixture(scope="module")
def style_current(tmp_path_factory):
    # the user would say yes to printing again: an offer after "keep my current style" shows up as a `rerender` call
    return _review(tmp_path_factory, "review-style-current", _ready_with_one_in_use,
                   "If the assistant asks which CV style to use, you want to keep the style you use now, unchanged: "
                   "pick \"Keep my current style\" (or the option that says the same), never The other door's and "
                   "never the new one. If it offers to print your prepared applications again, say yes.")


@pytest.fixture(scope="module", params=["building", "failed"])
def style_quiet(request, tmp_path_factory):
    """A build still running (its lock held by this test for the run) or one that failed."""
    with ExitStack() as stack:
        def seed(world):
            if request.param == "building":
                _run_record(world, "building", pid=1)
                stack.enter_context(lock.hold(home(world) / ".style" / "build.lock", 5))
            else:
                _run_record(world, "failed", result={"problems": ["the rebuilt CV never came close to the original"]})

        yield request.param, _review(tmp_path_factory, f"review-style-{request.param}", seed)


def _style_question(result) -> dict:
    """The one question that offered the styles: the first asked whose options name a CV style."""
    for ask in result["asked"]:
        for q in ask["questions"]:
            if any("door" in o.get("label", "").lower() for o in q.get("options", [])):
                return q
    raise AssertionError(f"no question offered the two styles: {result['asked']}")


def _offers_both_styles_and_recommends_neither(result) -> None:
    question = _style_question(result)
    labels = [o.get("label", "").lower() for o in question["options"]]
    assert any("door" in l for l in labels) and any("my cv" in l for l in labels), labels
    text = json.dumps(question).lower()
    assert "recommend" not in text, question
    said = [t for t in result["said"] if "recommend" in t.lower()]
    assert not said, said


def _shown_then_chosen(result) -> list[dict]:
    tools = result["tools"]
    assert "show_style" in tools and "use_style" in tools, tools
    assert tools.index("show_style") < tools.index("use_style"), tools
    read = [u["input"].get("file_path", "") for u in result["used"] if u["tool"] == "Read"]
    for style in ("default", "like"):
        assert any(f"/preview/{style}/cv_page_1.png" in path for path in read), read
    return _calls(result, "use_style")


def test_a_waiting_style_is_shown_before_it_is_chosen_with_neither_recommended(style_like):
    world, result = style_like
    uses = _shown_then_chosen(result)
    _offers_both_styles_and_recommends_neither(result)
    assert [c["args"].get("style") for c in uses] == ["like"], uses
    config = json.loads((home(world) / "profile" / "config.json").read_text(encoding="utf-8"))
    assert config.get("cv_template") == "profile/style/cv.template.html", config
    assert not (home(world) / "profile" / "style.next").exists()


def test_prepared_cvs_are_not_printed_again_without_a_yes(style_like):
    _, result = style_like
    assert not [c for c in _calls(result, "use_style") if c["args"].get("rerender")], result["calls"]
    assert not [t for t in result["tools"] if t in UNASKED], result["tools"]


def test_keeping_the_current_style_changes_nothing_and_prints_nothing_again(style_current):
    world, result = style_current
    uses = _shown_then_chosen(result)
    _offers_both_styles_and_recommends_neither(result)
    assert [c["args"].get("style") for c in uses] == ["current"], uses
    assert not [c for c in uses if c["args"].get("rerender")], uses
    config = json.loads((home(world) / "profile" / "config.json").read_text(encoding="utf-8"))
    assert config.get("cv_template") == "profile/style/cv.template.html", config
    assert not (home(world) / "profile" / "style.next").exists()
    kept = home(world) / "profile" / "style"
    assert sorted(p.name for p in kept.iterdir()) == sorted(templates.FILES.values())
    assert (kept / templates.FILES["cv_template"]).read_text(encoding="utf-8").endswith(IN_USE)


def test_a_build_running_or_failed_is_not_mentioned(style_quiet):
    state, (world, result) = style_quiet
    assert json.loads((home(world) / ".style" / "run.json").read_text(encoding="utf-8"))["state"] == state
    assert not {"show_style", "use_style", "build_style"} & set(result["tools"]), result["tools"]
    said = [s for s in result["said"] if re.search(r"\bstyles?\b", s, re.IGNORECASE)]
    assert not said, said
    assert result["tools"][-1] == "mark_reviewed", result["tools"]
