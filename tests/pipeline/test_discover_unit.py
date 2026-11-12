"""Step 2, `discover`: LinkedIn shows which employers hire for the keywords; they join the queue.

`linkedin.discover_run` is faked in every test; nothing here reaches LinkedIn.
"""

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from door.core import candidates, companies
from door.core import discovery_state as ds
from door.matching import title_fit
from door.scrapers.discovery import linkedin
from door.pipeline import discover
from profile_utils import write_config

VIEW = "https://www.linkedin.com/jobs/view/{}"


def employer(company, *links, detailed=False, job_ids=("1",), first_seen="2026-10-01T00:00:00+00:00"):
    return {"company": company, "titles": ["Data Scientist"], "job_ids": list(job_ids), "detailed": detailed,
            "first_seen": first_seen, "links": [*links, VIEW.format(job_ids[-1])]}


def outcome_of(result):
    if result["stopped"]:
        return "refused" if result["pushback"] else "error"
    return "ok"


@pytest.fixture
def fake(env, monkeypatch):
    f = type("Fake", (), {})()
    f.employers, f.stopped, f.pushback, f.raises, f.calls = [], None, False, None, []
    f.extra, f.gate = {}, None
    write_config(env.profile_dir, {"role_targets": ["data scientist"], "location": "Copenhagen",
                                   "linkedin_discovery": True})

    def discover_run(config, **kwargs):
        f.calls.append(kwargs)
        if f.gate is not None:
            f.gate.wait(5)
        if f.raises:
            raise f.raises
        result = {"employers": f.employers, "details": sum(1 for e in f.employers if e["detailed"]), "pages": 1,
                  "requests": 1 + sum(1 for e in f.employers if e["detailed"]), "stopped": f.stopped,
                  "pushback": f.pushback, "mode": kwargs["mode"], "mode_switched": False, "searched": [],
                  "search_complete": True, "first_429": None, "budget": kwargs["budget"],
                  "pause": list(kwargs["pause"]), "seconds": 12}
        result.update(f.extra)
        result["outcome"] = f.extra.get("outcome") or outcome_of(result)
        return result

    monkeypatch.setattr(linkedin, "discover_run", discover_run)
    return f


def run(env, **kw):
    return discover._discover_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir, **kw)


def test_an_employer_with_an_apply_link_is_queued_for_follow(env, fake):
    fake.employers = [employer("Pleo", "https://jobs.ashbyhq.com/pleo/abc", detailed=True, job_ids=("7", "8"))]

    block = run(env)

    entry = candidates.load(env.jobs_dir)["pleo"]
    assert entry["links"] == ["https://jobs.ashbyhq.com/pleo/abc", VIEW.format("8")]
    assert entry["sources"] == ["linkedin"] and entry["titles"] == ["Data Scientist"] and entry["job_ids"] == ["7", "8"]
    assert not candidates.needs_apply_link(entry)
    assert (block["step"], block["employers"], block["details"], block["queued"], block["skipped"]) == ("discover", 1, 1, 1, None)


def test_a_new_employer_is_queued_with_only_its_linkedin_link_for_follow_to_try_by_name(env, fake):
    fake.employers = [employer("Beta", job_ids=("5",))]

    block = run(env)

    entry = candidates.load(env.jobs_dir)["beta"]
    assert entry["links"] == [VIEW.format("5")] and entry["job_ids"] == ["5"]
    assert candidates.needs_apply_link(entry) and not candidates.name_tried(entry)
    assert block["queued"] == 1 and block["details"] == 0


def test_discover_adds_to_the_queue_and_never_resolves_or_follows(env, fake):
    fake.employers = [employer("Pleo", "https://jobs.ashbyhq.com/pleo/abc", detailed=True)]
    run(env)
    assert companies.load(env.profile_dir) == []


def test_an_easy_apply_employer_is_remembered_not_queued(env, fake):
    fake.employers = [employer("Acme", detailed=True)]
    block = run(env)
    assert candidates.load(env.jobs_dir) == {} and block["easy_apply"] == 1
    assert ds.load(env.jobs_dir, "linkedin")["seen"]["acme"]["outcome"] == "easy_apply"


def test_only_employers_follow_could_not_resolve_by_name_are_passed_as_pending(env, fake):
    now = datetime.now(timezone.utc)
    queue = {}
    candidates.add(queue, "Pleo", links=["https://jobs.ashbyhq.com/pleo/abc", VIEW.format("1")], titles=[],
                   source="linkedin", now=now)
    candidates.add(queue, "Beta", links=[VIEW.format("2")], titles=["DS"], source="linkedin", now=now, job_ids=["2"])
    candidates.add(queue, "Gamma", links=[VIEW.format("3")], titles=[], source="linkedin", now=now, job_ids=["3"])
    candidates.mark_name_tried(queue["gamma"], now)
    candidates.save(env.jobs_dir, queue)

    run(env)

    call = fake.calls[-1]
    assert list(call["pending"]) == ["gamma"] and call["pending"]["gamma"]["job_ids"] == ["3"]
    assert "Pleo" in call["known_companies"] and "Gamma" not in call["known_companies"]


def test_settled_and_seen_employers_are_known_and_never_queued(env, fake):
    items = []
    companies.record(items, "BEC", feed=("hr_manager", "bec"), status="followed", found_via="manual")
    companies.save(env.profile_dir, items)
    state = ds.load(env.jobs_dir, "linkedin")
    ds.record(state, "Easy Co", "easy_apply", datetime.now(timezone.utc))
    ds.save(env.jobs_dir, "linkedin", state)
    fake.employers = [employer("BEC"), employer("Easy Co"), employer("Pleo", "https://x.ashbyhq.com/p", detailed=True)]

    run(env)

    assert {"BEC", "easy co"} <= set(fake.calls[-1]["known_companies"])
    assert set(candidates.load(env.jobs_dir)) == {"pleo"}


def test_a_clean_run_stamps_last_run_and_a_stopped_one_does_not(env, fake):
    run(env)
    assert ds.load(env.jobs_dir, "linkedin")["last_run"]
    state = ds.load(env.jobs_dir, "linkedin")
    state.pop("last_run")
    ds.save(env.jobs_dir, "linkedin", state)
    fake.stopped = "HTTP 500"
    block = run(env)
    assert "last_run" not in ds.load(env.jobs_dir, "linkedin") and block["stopped"] == "HTTP 500"
    assert "stopped: HTTP 500" in block["summary"]


def test_a_refusal_rests_discovery(env, fake):
    fake.stopped, fake.pushback = "HTTP 429", True
    run(env)
    assert ds.load(env.jobs_dir, "linkedin")["pushback_at"]


def test_resting_after_a_refusal_skips_the_step_with_the_time(env, fake, progress_events):
    until = datetime.now(timezone.utc) - timedelta(hours=1)
    ds.save(env.jobs_dir, "linkedin", {"pushback_at": until.isoformat(), "seen": {}})
    block = run(env)
    assert fake.calls == []
    assert block["skipped"].startswith("LinkedIn resting until ")
    assert [(e.site, e.outcome) for e in progress_events if e.stage == "step"] == [("discover", "skipped")]


def test_turned_off_skips_the_step(env, fake):
    write_config(env.profile_dir, {"linkedin_discovery": False})
    block = run(env)
    assert fake.calls == [] and block["skipped"] == "linkedin_discovery is off"  # profession.hu: not for dk


def test_a_crash_is_reported_in_the_block_and_never_raised(env, fake, progress_events):
    fake.raises = RuntimeError("boom")
    block = run(env)
    assert "boom" in block["error"] and block["skipped"] is None
    assert progress_events[-1].outcome == "failed"


def test_since_follows_the_last_run(env, fake):
    ds.save(env.jobs_dir, "linkedin", {"last_run": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(), "seen": {}})
    run(env)
    assert fake.calls[-1]["since"] is not None


# --------------------------------------------------------------------------- #
# pace, history and mode
# --------------------------------------------------------------------------- #

def test_a_fresh_state_runs_at_the_default_budget_and_pause_one_query_per_keyword(env, fake):
    run(env)
    call = fake.calls[-1]
    assert call["budget"] == 150 and call["pause"] == (2.0, 4.0) and call["mode"] == "rotate"
    assert call["rotation"] == title_fit.keywords(json.loads((env.profile_dir / "config.json").read_text()))  # all of them


def test_every_run_is_logged_and_the_summary_names_the_budget_and_pace(env, fake):
    fake.employers = [employer("Pleo", "https://jobs.ashbyhq.com/pleo/abc", detailed=True)]
    block = run(env)
    [entry] = ds.load(env.jobs_dir, "linkedin")["history"]
    assert (entry["requests"], entry["pages"], entry["job_pages"], entry["outcome"], entry["mode"]) == (2, 1, 1, "ok", "rotate")
    assert entry["budget"] == 150 and entry["pause"] == [2.0, 4.0] and entry["first_429"] is None
    assert block["requests"] == 2 and block["budget"] == 150 and block["pause"] == [2.0, 4.0] and block["mode"] == "rotate"
    assert block["summary"] == "1 employers, 1 queued, 1 pages + 1 job pages (2/150 requests, 2-4 s pause, rotate)"


def test_a_refusal_halves_the_next_budget_and_doubles_the_next_pause(env, fake):
    fake.stopped, fake.pushback = "HTTP 429", True
    fake.extra = {"first_429": {"after_requests": 0, "after_s": 3}, "requests": 1}
    run(env)
    [entry] = ds.load(env.jobs_dir, "linkedin")["history"]
    assert entry["outcome"] == "refused" and entry["first_429"] == {"after_requests": 0, "after_s": 3}
    state = ds.load(env.jobs_dir, "linkedin")
    state.pop("pushback_at")  # the day has passed
    ds.save(env.jobs_dir, "linkedin", state)
    fake.stopped, fake.pushback, fake.extra = None, False, {}

    block = run(env)

    assert fake.calls[-1]["budget"] == 75 and fake.calls[-1]["pause"] == (4.0, 8.0)
    assert "75" in block["summary"] and "4-8 s pause" in block["summary"]


def test_a_run_that_made_no_request_logs_nothing(env, fake):
    fake.extra = {"requests": 0, "pages": 0}
    run(env)
    assert "history" not in ds.load(env.jobs_dir, "linkedin")


def test_rotate_mode_lines_up_every_keyword_and_advances_past_the_ones_searched(env, fake):
    write_config(env.profile_dir, {"role_targets": ["a", "b", "c", "d", "e"],
                                   "location": "Copenhagen", "linkedin_discovery": True})
    state = ds.load(env.jobs_dir, "linkedin")
    state["mode"] = "rotate"
    ds.save(env.jobs_dir, "linkedin", state)
    fake.extra = {"searched": ["a", "b", "c"]}

    run(env)
    call = fake.calls[-1]
    assert call["mode"] == "rotate" and call["rotation"] == ["a", "b", "c", "d", "e"]
    assert set(call["keyword_since"]) >= {"a", "b", "c"}
    after = ds.load(env.jobs_dir, "linkedin")
    assert after["rotation"] == 3 and set(after["searched"]) == {"a", "b", "c"}

    run(env)
    assert fake.calls[-1]["rotation"] == ["d", "e", "a", "b", "c"]


def test_a_keyword_cut_short_by_the_budget_is_not_marked_searched_and_comes_back_first(env, fake):
    write_config(env.profile_dir, {"role_targets": ["a", "b", "c", "d"],
                                   "location": "Copenhagen", "linkedin_discovery": True})
    state = ds.load(env.jobs_dir, "linkedin")
    state["mode"] = "rotate"
    ds.save(env.jobs_dir, "linkedin", state)
    fake.extra = {"searched": ["a"], "search_complete": False, "outcome": "budget"}
    run(env)
    after = ds.load(env.jobs_dir, "linkedin")
    assert after["rotation"] == 1 and set(after["searched"]) == {"a"}


def test_the_combined_form_failing_where_one_keyword_works_switches_to_rotation_for_good(env, fake):
    fake.extra = {"mode": "rotate", "mode_switched": True, "searched": ["data scientist"]}
    block = run(env)
    assert ds.load(env.jobs_dir, "linkedin")["mode"] == "rotate" and block["mode_switched"] is True and block["mode"] == "rotate"
    run(env)
    assert fake.calls[-1]["mode"] == "rotate"


# --------------------------------------------------------------------------- #
# in the background: network on a worker thread, ledgers on the caller's
# --------------------------------------------------------------------------- #

def test_begin_returns_at_once_and_writes_nothing_until_it_is_finished(env, fake, progress_events):
    fake.gate = threading.Event()
    fake.employers = [employer("Beta", job_ids=("5",))]

    handle = discover.begin(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)

    assert handle.skipped is None and not handle.ready()
    assert [(e.site, e.outcome) for e in progress_events if e.stage == "step"] == [("discover", "start")]
    fake.gate.set()
    handle.wait_ready(5)
    assert handle.ready()
    assert candidates.load(env.jobs_dir) == {} and ds.load(env.jobs_dir, "linkedin").get("last_run") is None  # the thread wrote nothing

    block = handle.finish()

    assert set(candidates.load(env.jobs_dir)) == {"beta"} and ds.load(env.jobs_dir, "linkedin")["last_run"]
    assert block["queued"] == 1 and block["employers"] == 1
    assert [(e.site, e.outcome) for e in progress_events if e.stage == "step"][-1] == ("discover", "done")


@pytest.mark.parametrize("stopped, pushback, outcome, raises, text", [
    (None, False, None, None, "85/150 requests, search complete; queuing at the next step"),
    (None, False, "budget", None, "85/150 requests, budget spent; queuing at the next step"),
    ("HTTP 429", True, None, None, "85/150 requests, stopped: HTTP 429; queuing at the next step"),
    (None, False, None, RuntimeError("boom"), "failed: RuntimeError: boom"),
])
def test_the_thread_says_how_its_requests_ended_before_finish_queues_them(
        env, fake, progress_events, stopped, pushback, outcome, raises, text):
    fake.stopped, fake.pushback, fake.raises = stopped, pushback, raises
    fake.extra = {"requests": 85, "budget": 150, **({"outcome": outcome} if outcome else {})}
    handle = discover.begin(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)
    handle.wait_ready(5)

    assert [(e.message, e.outcome) for e in progress_events if e.stage == "li_end"] == \
        [(text, "failed" if raises else "done")]
    assert [e.outcome for e in progress_events if e.stage == "step"] == ["start"]  # not done until finish
    handle.finish()


def test_finish_keeps_what_the_other_steps_queued_meanwhile(env, fake):
    fake.gate = threading.Event()
    fake.employers = [employer("Beta", job_ids=("5",))]
    handle = discover.begin(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)
    queue = {}
    candidates.add(queue, "Acme", links=["https://www.jobindex.dk/jobannonce/1"], titles=[], source="jobindex",
                   now=datetime.now(timezone.utc))
    candidates.save(env.jobs_dir, queue)  # what `search` does meanwhile
    items = []
    companies.record(items, "Beta", feed=("lever", "beta"), status="followed", found_via="manual")
    companies.save(env.profile_dir, items)  # ... and an employer got settled
    fake.gate.set()

    handle.finish()

    assert set(candidates.load(env.jobs_dir)) == {"acme"}


def test_finish_waits_for_the_thread(env, fake):
    fake.gate = threading.Event()
    threading.Timer(0.05, fake.gate.set).start()
    handle = discover.begin(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)
    assert handle.finish()["error"] is None and handle.ready()


def test_begin_on_a_resting_step_starts_no_thread(env, fake, progress_events):
    ds.save(env.jobs_dir, "linkedin", {"pushback_at": datetime.now(timezone.utc).isoformat(), "seen": {}})
    handle = discover.begin(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)
    assert handle.skipped.startswith("LinkedIn resting until ") and handle.ready() and fake.calls == []
    assert handle.finish()["skipped"] == handle.skipped
    assert [(e.site, e.outcome) for e in progress_events if e.stage == "step"] == [("discover", "skipped")]


def test_cancel_stops_the_thread_and_finish_keeps_what_it_read(env, fake, monkeypatch):
    seen_stop = []

    def discover_run(config, **kwargs):
        seen_stop.append(kwargs["stop"])
        kwargs["stop"].wait(5)
        return {"employers": [employer("Beta", job_ids=("5",))], "details": 0, "pages": 1, "requests": 1,
                "stopped": "cancelled", "pushback": False, "outcome": "cancelled", "mode": "combined",
                "mode_switched": False, "searched": [], "search_complete": False, "first_429": None,
                "budget": 15, "pause": [60.0, 120.0], "seconds": 1}

    monkeypatch.setattr(linkedin, "discover_run", discover_run)
    handle = discover.begin(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)

    handle.cancel()
    block = handle.finish()

    assert seen_stop[0].is_set() and block["stopped"] == "cancelled"
    assert set(candidates.load(env.jobs_dir)) == {"beta"} and "last_run" not in ds.load(env.jobs_dir, "linkedin")
    assert ds.load(env.jobs_dir, "linkedin")["history"][0]["outcome"] == "cancelled"


def test_a_crash_in_the_thread_is_reported_by_finish_not_raised(env, fake, progress_events):
    fake.raises = RuntimeError("boom")
    handle = discover.begin(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)
    block = handle.finish()
    assert "boom" in block["error"] and progress_events[-1].outcome == "failed"


# --------------------------------------------------------------------------- #
# sources: the block's per-source breakdown, the migration of the old state file
# --------------------------------------------------------------------------- #

def test_the_block_keeps_its_fields_and_breaks_down_by_source(env, fake):
    fake.employers = [employer("Pleo", "https://jobs.ashbyhq.com/pleo/abc", detailed=True), employer("Acme", detailed=True)]
    block = run(env)
    for key in ("step", "skipped", "employers", "details", "pages", "requests", "queued", "easy_apply", "budget", "pause",
                "mode", "mode_switched", "search_complete", "outcome", "stopped", "error", "elapsed_s", "summary"):
        assert key in block
    assert (block["employers"], block["queued"], block["easy_apply"]) == (2, 1, 1)
    src = block["sources"]["linkedin"]
    assert (src["employers"], src["queued"], src["requests"], src["budget"], src["pause"], src["outcome"]) == \
        (2, 1, 3, 150, [2.0, 4.0], "ok")
    assert src["stopped"] is None and src["skipped"] is None and src["error"] is None


def test_the_old_state_file_is_migrated_on_the_first_run(env, fake):
    env.jobs_dir.mkdir(parents=True, exist_ok=True)
    (env.jobs_dir / "linkedin_discovery.json").write_text(json.dumps(
        {"seen": {}, "pace": {"budget": 75, "factor": 2, "clean_runs": 0}}))
    run(env)
    assert fake.calls[-1]["budget"] == 75 and fake.calls[-1]["pause"] == (4.0, 8.0)
    assert (env.jobs_dir / "discovery" / "linkedin.json").exists()


# --- profession.hu, the second source ---------------------------------------------------------

def _profession_employer(company, *ids):
    return {"company": company, "titles": ["Data Scientist"], "job_ids": [], "detailed": False,
            "first_seen": "2026-10-20T00:00:00+00:00",
            "links": [f"https://www.profession.hu/allas/data-scientist-{i}" for i in ids]}


@pytest.fixture
def prof(env, monkeypatch):
    from door.scrapers.discovery import profession

    p = type("Prof", (), {})()
    p.employers, p.stopped, p.pushback, p.calls = [], None, False, []
    write_config(env.profile_dir, {"role_targets": ["data scientist"], "location": "Budapest",
                                   "profession_discovery": True})

    def run_(config, **kwargs):
        p.calls.append(kwargs)
        return {"employers": p.employers, "details": 0, "pages": 2, "requests": 2, "stopped": p.stopped,
                "pushback": p.pushback, "mode": "rotate", "mode_switched": False, "searched": ["data scientist"],
                "search_complete": p.stopped is None, "first_429": None, "budget": kwargs["budget"],
                "pause": list(kwargs["pause"]), "seconds": 5,
                "outcome": ("refused" if p.pushback else "error") if p.stopped else "ok"}

    monkeypatch.setattr(profession, "run", run_)
    return p


def test_profession_employers_are_queued_with_their_ad_link_under_their_source(env, prof):
    prof.employers = [_profession_employer("Trendency Zrt.", "1"), _profession_employer("Alfa Kft.", "2")]

    block = run(env)

    queue = candidates.load(env.jobs_dir)
    entry = queue[companies.name_key("Trendency Zrt.")]
    assert entry["sources"] == ["profession"] and entry["titles"] == ["Data Scientist"]
    assert entry["links"] == ["https://www.profession.hu/allas/data-scientist-1"]
    assert not candidates.awaiting_job_page(entry) and len(queue) == 2
    assert block["sources"]["profession"]["employers"] == 2 and block["sources"]["profession"]["queued"] == 2
    assert block["sources"]["linkedin"]["skipped"] == "linkedin_discovery is off"
    assert "profession: 2 employers, 2 queued" not in block["summary"]  # one source ran: no per-source tail
    assert (env.jobs_dir / "discovery" / "profession.json").exists()
    assert "data scientist" in ds.load(env.jobs_dir, "profession")["searched"]


def test_profession_is_not_run_for_a_danish_profile(env, prof):
    write_config(env.profile_dir, {"role_targets": ["data scientist"], "location": "Copenhagen",
                                   "profession_discovery": True})
    block = run(env)
    assert prof.calls == [] and block["sources"]["profession"]["skipped"] == "not for dk"


def test_a_profession_refusal_rests_only_profession(env, prof):
    prof.stopped, prof.pushback = "HTTP 429", True
    run(env)
    assert ds.load(env.jobs_dir, "profession")["pushback_at"]
    assert "pushback_at" not in ds.load(env.jobs_dir, "linkedin")
    block = run(env)
    assert block["sources"]["profession"]["skipped"].startswith("profession.hu resting until ") and len(prof.calls) == 1
