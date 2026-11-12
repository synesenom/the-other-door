"""Step 3, `follow`: the queued employers' feeds, found and recorded.

HTTP is mocked with `responses` (anything else is refused), DNS through `companies._cname`.
"""

import re
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
import responses

from door.commands import companies as companies_cmd
from door.core import candidates, companies
from door.pipeline import follow
from door.scrapers import _parallel
from profile_utils import write_config

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def queue_up(env, name, *links, source="linkedin", titles=("Data Scientist",), when=NOW, **extra):
    queue = candidates.load(env.jobs_dir)
    candidates.add(queue, name, links=list(links), titles=list(titles), source=source, now=when, **extra)
    candidates.save(env.jobs_dir, queue)


def run(env, **kw):
    return follow._follow_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir, **kw)


def listed(env):
    return {c.name: c for c in companies.load(env.profile_dir)}


def test_an_employer_with_a_feed_link_is_followed_and_leaves_the_queue(env):
    queue_up(env, "Pleo", "https://jobs.ashbyhq.com/pleo/abc", source="linkedin")

    block = run(env, probe=False)

    pleo = listed(env)["Pleo"]
    assert pleo.status == "followed" and (pleo.feed.platform, pleo.feed.id) == ("ashby", "pleo")
    assert pleo.found_via == "linkedin" and pleo.evidence
    assert candidates.load(env.jobs_dir) == {}
    assert block["followed"] == [{"company": "Pleo", "platform": "ashby", "entry": "pleo"}]
    assert block["checked"] == 1 and block["summary"] == "1 candidates: 1 followed, 0 unfollowable, 0 unresolved"


def test_found_via_is_the_source_that_queued_the_employer(env):
    queue_up(env, "Pleo", "https://jobs.ashbyhq.com/pleo/abc", source="hellowork")
    queue_up(env, "Lego", "https://jobs.lever.co/lego/1", source="workable")
    run(env, probe=False)
    assert (listed(env)["Pleo"].found_via, listed(env)["Lego"].found_via) == ("hellowork", "workable")


def test_an_oracle_career_site_is_followed_on_its_host_and_site(env):
    queue_up(env, "Danske Bank", "https://ejqi.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience/en/sites/CX_1001")
    block = run(env, probe=False)
    bank = listed(env)["Danske Bank"]
    assert bank.status == "followed" and (bank.feed.platform, bank.feed.id) == ("oracle_hcm", "ejqi.fa.ocs.oraclecloud.eu/CX_1001")
    assert block["followed"][0]["company"] == "Danske Bank" and candidates.load(env.jobs_dir) == {}


def test_a_platform_that_cannot_be_followed_is_recorded_with_the_reason(env):
    queue_up(env, "Danske Bank", "https://ejqi.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience/x")
    block = run(env, probe=False)
    bank = listed(env)["Danske Bank"]
    assert bank.status == "unfollowable" and "names no career site" in bank.reason and bank.feed is None
    assert bank.refusal == "cant_yet"
    assert block["unfollowable"][0]["company"] == "Danske Bank" and candidates.load(env.jobs_dir) == {}


@responses.activate
def test_an_employer_with_no_feed_is_recorded_unresolved_not_asked_again(env):
    queue_up(env, "Acme", "https://acme.dk/jobs/1")
    responses.add(responses.GET, "https://acme.dk/jobs/1", body="<html>nothing</html>")
    responses.add(responses.GET, re.compile(r".*"), status=404)

    block = run(env)

    acme = listed(env)["Acme"]
    assert acme.status == "unresolved" and acme.reason == "no job feed found" and acme.found_via == "linkedin"
    assert block["unresolved"] == [{"company": "Acme", "reason": "no job feed found"}]
    assert companies.is_settled(companies.load(env.profile_dir), "Acme")


@responses.activate
def test_an_employer_with_only_job_board_links_is_probed_by_name_and_recorded(env):
    queue_up(env, "Trustpilot", "https://www.jobindex.dk/jobannonce/1", source="jobindex")
    responses.add(responses.GET, re.compile(r"https://boards-api\.greenhouse\.io/v1/boards/trustpilot/jobs.*"),
                  json={"jobs": [{"id": 1, "title": "Data Scientist"}]})
    block = run(env)
    assert listed(env)["Trustpilot"].feed.platform == "greenhouse" and block["followed"][0]["entry"] == "trustpilot"


def test_with_no_employer_link_and_nothing_found_the_reason_says_so(env):
    queue_up(env, "Acme", "https://www.jobindex.dk/jobannonce/1", source="jobindex")
    run(env, probe=False)
    assert "no employer link" in listed(env)["Acme"].reason


def test_a_linkedin_employer_is_tried_by_name_first_and_parked_when_that_finds_nothing(env):
    queue_up(env, "Beta", "https://www.linkedin.com/jobs/view/5", source="linkedin", job_ids=["5"])

    block = run(env, probe=False)

    entry = candidates.load(env.jobs_dir)["beta"]
    assert "Beta" not in listed(env) and candidates.awaiting_job_page(entry)  # parked for discover's job page
    assert block["checked"] == 1 and block["kept"] == 1 and block["unresolved"] == [] and block["errors"] == []
    assert block["summary"] == "1 candidates: 0 followed, 0 unfollowable, 0 unresolved, 1 waiting for an apply link"


def test_a_parked_linkedin_employer_is_not_tried_again_and_stays_queued(env):
    queue_up(env, "Beta", "https://www.linkedin.com/jobs/view/5", source="linkedin", job_ids=["5"])
    queue = candidates.load(env.jobs_dir)
    candidates.mark_name_tried(queue["beta"], NOW)
    candidates.save(env.jobs_dir, queue)

    block = run(env, probe=False)

    assert block["kept"] == 1 and block["checked"] == 0 and "Beta" not in listed(env)
    assert "beta" in candidates.load(env.jobs_dir)
    assert block["summary"] == "nothing to check, 1 waiting for an apply link"


def test_a_linkedin_employer_found_by_name_is_followed_without_its_job_page(env, monkeypatch):
    queue_up(env, "Beta", "https://www.linkedin.com/jobs/view/5", source="linkedin", job_ids=["5"])
    seen = {}

    def classify(session, company, followed, ctx=None):
        seen.update(company)
        return "suggestions", {"company": "Beta", "platform": "lever", "entry": "beta", "config_key": "lever_companies",
                               "evidence": "name probe", "postings": 1, "found_via": "linkedin"}

    monkeypatch.setattr(companies_cmd, "_classify", classify)

    block = run(env)

    assert listed(env)["Beta"].feed.id == "beta" and candidates.load(env.jobs_dir) == {}
    assert block["followed"] == [{"company": "Beta", "platform": "lever", "entry": "beta"}] and block["kept"] == 0
    assert seen["links"] == ["https://www.linkedin.com/jobs/view/5"] and seen["sources"] == {"linkedin"}


def test_a_dry_run_does_not_park_anything(env):
    queue_up(env, "Beta", "https://www.linkedin.com/jobs/view/5", source="linkedin", job_ids=["5"])
    run(env, probe=False, dry_run=True)
    assert not candidates.name_tried(candidates.load(env.jobs_dir)["beta"])


def test_linkedin_employers_are_checked_in_their_own_groups_not_one_serial_queue(env):
    from door.pipeline.follow import _group

    a = {"name": "Alpha", "links": ["https://www.linkedin.com/jobs/view/1"], "sources": ["linkedin"], "titles": []}
    b = {"name": "Beta", "links": ["https://www.linkedin.com/jobs/view/2"], "sources": ["linkedin"], "titles": []}
    assert _group(a) != _group(b)


def test_employers_the_list_already_settles_are_dropped_without_a_check(env, monkeypatch):
    items = []
    companies.record(items, "Pleo", feed=("ashby", "pleo"), status="followed", found_via="manual")
    companies.record(items, "Old Co", feed=None, status="unresolved", found_via="jobindex", reason="x",
                     now=(NOW - timedelta(days=10)).isoformat())
    companies.save(env.profile_dir, items)
    queue_up(env, "Pleo", "https://jobs.ashbyhq.com/pleo/abc")
    queue_up(env, "Old Co", "https://oldco.dk/jobs")
    monkeypatch.setattr(companies_cmd, "_classify", lambda *a, **k: pytest.fail("must not check"))

    block = run(env, probe=False)

    assert block["settled"] == 2 and block["checked"] == 0 and candidates.load(env.jobs_dir) == {}


def test_an_unresolved_employer_is_checked_again_after_ninety_days(env):
    items = []
    companies.record(items, "Pleo", feed=None, status="unresolved", found_via="jobindex", reason="x",
                     now=(NOW - timedelta(days=100)).isoformat())
    companies.save(env.profile_dir, items)
    queue_up(env, "Pleo", "https://jobs.ashbyhq.com/pleo/abc")
    run(env, probe=False)
    assert listed(env)["Pleo"].status == "followed"


def test_entries_not_seen_for_max_age_days_are_dropped_unchecked(env):
    queue_up(env, "Stale Co", "https://jobs.ashbyhq.com/stale/1", when=NOW - timedelta(days=45))
    queue_up(env, "Fresh Co", "https://jobs.ashbyhq.com/fresh/1", when=NOW - timedelta(days=5))
    block = run(env, probe=False)
    assert block["expired"] == 1 and set(listed(env)) == {"Fresh Co"} and candidates.load(env.jobs_dir) == {}


def test_a_dry_run_reports_and_writes_nothing(env):
    queue_up(env, "Pleo", "https://jobs.ashbyhq.com/pleo/abc")
    before = (env.jobs_dir / "candidates.json").read_text()

    block = run(env, probe=False, dry_run=True)

    assert block["dry_run"] and block["followed"][0]["company"] == "Pleo"
    assert block["results"][0]["status"] == "followed" and block["summary"].startswith("would record ")
    assert not (env.profile_dir / "companies.json").exists()
    assert (env.jobs_dir / "candidates.json").read_text() == before


def test_a_check_that_blows_up_keeps_the_employer_queued_and_the_others_go_on(env, monkeypatch):
    queue_up(env, "Boom", "https://boom.dk/jobs/1")
    queue_up(env, "Pleo", "https://jobs.ashbyhq.com/pleo/abc")
    real = companies_cmd._classify

    def classify(session, company, followed, hr):
        if company["company"] == "Boom":
            raise RuntimeError("kaput")
        return real(session, company, followed, hr)

    monkeypatch.setattr(companies_cmd, "_classify", classify)

    block = run(env, probe=False)

    assert block["errors"] == [{"company": "Boom", "error": "RuntimeError: kaput"}]
    assert set(listed(env)) == {"Pleo"} and set(candidates.load(env.jobs_dir)) == {"boom"}
    assert block["summary"].endswith("1 failed")


def test_an_employer_found_under_another_name_is_one_employer(env):
    items = []
    companies.record(items, "Pleo ApS", feed=("ashby", "pleo"), status="followed", found_via="manual")
    companies.save(env.profile_dir, items)
    queue_up(env, "Pleo Technologies", "https://jobs.ashbyhq.com/pleo/abc")
    run(env, probe=False)
    assert len(companies.load(env.profile_dir)) == 1


# --- parallelism -------------------------------------------------------------------------------

def _slow_classify(monkeypatch, spans):
    """A `_classify` that records when it ran and for which host."""
    def classify(session, company, followed, hr):
        start = time.monotonic()
        threading.Event().wait(0.05)
        spans.append((follow._group({"links": company["links"], "name": company["company"]}), start, time.monotonic()))
        return None

    monkeypatch.setattr(companies_cmd, "_classify", classify)


def _max_overlap(spans):
    events = sorted([(s, 1) for _, s, e in spans] + [(e, -1) for _, s, e in spans])
    level = best = 0
    for _, delta in events:
        level += delta
        best = max(best, level)
    return best


def test_different_hosts_are_checked_side_by_side_and_one_host_one_at_a_time(env, monkeypatch):
    spans = []
    _slow_classify(monkeypatch, spans)
    for i in range(3):
        queue_up(env, f"A{i}", f"https://jobs.a.example.dk/{i}")
        queue_up(env, f"B{i}", f"https://jobs.b.example.com/{i}")
    run(env, probe=False)
    by_host = {}
    for host, s, e in spans:
        by_host.setdefault(host, []).append((s, e))
    assert set(by_host) == {"jobs.a.example.dk", "jobs.b.example.com"}
    for host_spans in by_host.values():
        assert _max_overlap([("", s, e) for s, e in host_spans]) == 1
    assert _max_overlap(spans) == 2


def test_at_most_per_provider_hosts_of_one_provider_run_at_once(env, monkeypatch):
    spans = []
    _slow_classify(monkeypatch, spans)
    for i in range(8):
        queue_up(env, f"Co{i}", f"https://co{i}.teamtailor.com/jobs/1")
    run(env, probe=False)
    assert _max_overlap(spans) == _parallel.PER_PROVIDER


def test_scrape_workers_one_runs_them_one_after_another(env, monkeypatch):
    write_config(env.profile_dir, {"scrape_workers": 1})
    spans = []
    _slow_classify(monkeypatch, spans)
    for i in range(4):
        queue_up(env, f"Co{i}", f"https://co{i}.example.dk/jobs/1")
    run(env, probe=False)
    assert _max_overlap(spans) == 1


# --- progress ------------------------------------------------------------------------------------

def test_the_step_counts_candidates_checked(env, progress_events):
    for i in range(3):
        queue_up(env, f"Co{i}", f"https://jobs.ashbyhq.com/co{i}/1")
    run(env, probe=False)
    counts = sorted((e.done, e.total) for e in progress_events if e.stage == "candidate")
    assert counts == [(1, 3), (2, 3), (3, 3)]
    start = next(e for e in progress_events if e.stage == "step" and e.outcome == "start")
    assert (start.site, start.total) == ("follow", 3)


# --- recorded as it goes ---------------------------------------------------------------------------

def test_an_interrupted_follow_has_recorded_the_employers_already_checked(env, monkeypatch):
    write_config(env.profile_dir, {"scrape_workers": 1, "location": "Copenhagen"})
    for i in range(4):
        queue_up(env, f"Co{i}", f"https://jobs.ashbyhq.com/co{i}/abc")
    real = companies_cmd._classify
    seen = []

    def classify(session, company, followed, hr):
        if len(seen) == 3:
            raise KeyboardInterrupt  # not an Exception: nothing downstream may swallow it
        seen.append(company["company"])
        return real(session, company, followed, hr)

    monkeypatch.setattr(companies_cmd, "_classify", classify)

    with pytest.raises(KeyboardInterrupt):
        run(env, probe=False)

    assert set(listed(env)) == set(seen) and len(seen) == 3
    assert set(candidates.load(env.jobs_dir)) == {"co3"}  # the three recorded are dequeued, the fourth waits


# --- a dormant employer seen again ------------------------------------------------------------------------

def _dormant(env, name="Acme"):
    items = []
    companies.record(items, name, feed=("lever", "acme"), status="followed", found_via="jobindex",
                     now="2026-01-01T00:00:00+00:00")
    companies.retire_idle(items, 90, NOW)
    companies.save(env.profile_dir, items)


def test_a_dormant_employer_seen_with_a_fitting_ad_is_followed_again_without_detection(env, monkeypatch):
    _dormant(env)
    queue_up(env, "Acme", "https://www.jobindex.dk/jobannonce/1", source="jobindex")
    monkeypatch.setattr(companies_cmd, "_classify", lambda *a, **k: pytest.fail("its feed is known"))

    block = run(env)

    acme = listed(env)["Acme"]
    assert (acme.status, acme.reason, acme.feed.id, acme.found_via) == ("followed", None, "acme", "jobindex")
    assert acme.last_relevant is not None
    assert block["followed"] == [{"company": "Acme", "platform": "lever", "entry": "acme"}]
    assert candidates.load(env.jobs_dir) == {}


def test_a_dormant_linkedin_employer_needs_no_apply_link_to_be_followed_again(env):
    _dormant(env)
    queue_up(env, "Acme", "https://www.linkedin.com/jobs/view/1", source="linkedin", job_ids=["1"])
    run(env)
    assert listed(env)["Acme"].status == "followed"


def test_a_late_follow_reports_late_events_so_the_display_folds_it_into_the_follow_line(env, progress_events):
    queue_up(env, "Pleo", "https://jobs.ashbyhq.com/pleo/abc", source="linkedin")
    run(env, probe=False, late=True)
    assert [(e.stage, e.outcome) for e in progress_events if e.outcome in ("start", "done")] == [("late", "start"), ("late", "done")]


def test_employers_are_tried_on_the_career_hosts_of_the_profiles_country(env, monkeypatch):
    queue_up(env, "Beta", "https://www.linkedin.com/jobs/view/5", source="linkedin", job_ids=["5"])
    contexts = []

    def classify(session, company, followed, ctx=None):
        contexts.append(ctx)
        return None

    monkeypatch.setattr(companies_cmd, "_classify", classify)

    run(env)

    assert contexts and contexts[0].hosts == companies_cmd._host_guesses("Copenhagen")
    assert "karriere.{s}.dk" in contexts[0].hosts


# --- the state's shared portal is one employer (#308) ---------------------------------------------------------

_PORTAL = "Statens Rekrutteringsløsning"
_PORTAL_FEED = ("hr_manager", "statensrekrutteringsloesning_tr")


def _agency_link(project):
    return f"https://candidate.hr-manager.net/ApplicationInit.aspx?cid=3010&ProjectId={project}&DepartmentId=2&MediaId=5"


def _follow_portal(env):
    items = []
    companies.record(items, _PORTAL, feed=_PORTAL_FEED, status="followed", found_via="manual")
    companies.save(env.profile_dir, items)


def test_agencies_on_a_followed_portal_are_settled_not_followed(env):
    _follow_portal(env)
    queue_up(env, "Trafikstyrelsen", _agency_link(1))
    queue_up(env, "Forsvaret", _agency_link(2))

    block = run(env)

    assert block["followed"] == [] and block["settled"] == 2
    assert list(listed(env)) == [_PORTAL]
    assert "Trafikstyrelsen" in listed(env)[_PORTAL].evidence and "Forsvaret" in listed(env)[_PORTAL].evidence
    assert candidates.load(env.jobs_dir) == {}


def test_three_agencies_on_a_new_portal_follow_it_once(env):
    for i, name in enumerate(["Trafikstyrelsen", "Forsvaret", "GEUS"]):
        queue_up(env, name, _agency_link(i))

    block = run(env)

    assert len(block["followed"]) == 1 and block["settled"] == 2
    assert list(listed(env)) == [_PORTAL]


def test_a_dry_run_counts_the_same_and_writes_nothing(env):
    for i, name in enumerate(["Trafikstyrelsen", "Forsvaret"]):
        queue_up(env, name, _agency_link(i))

    block = run(env, dry_run=True)

    assert len(block["followed"]) == 1 and block["settled"] == 1
    assert listed(env) == {} and len(candidates.load(env.jobs_dir)) == 2


def test_an_unresolved_agency_of_the_portal_is_looked_at_again(env):
    items = []
    companies.record(items, "Trafikstyrelsen", feed=None, status="unresolved", found_via="linkedin",
                     reason="the link names no alias", now=companies.now_iso())
    companies.save(env.profile_dir, items)
    _follow_portal(env)
    queue_up(env, "Trafikstyrelsen", _agency_link(1))

    block = run(env)

    assert block["settled"] == 1
    assert list(listed(env)) == [_PORTAL]


def test_an_unresolved_employer_is_still_held_for_ninety_days(env):
    items = []
    companies.record(items, "Acme", feed=None, status="unresolved", found_via="linkedin", reason="x",
                     now=companies.now_iso())
    companies.save(env.profile_dir, items)
    queue_up(env, "Acme", "https://acme.example/jobs/1")

    block = run(env, probe=False)

    assert block["checked"] == 0 and block["settled"] == 1


def test_found_via_names_every_board_and_discovery_source(env):
    from door.core import discovery_sources, sites
    values = companies.found_via_values()
    assert {"manual", "ai"} <= set(values)
    assert {s.name for s in sites.SITES.values() if s.board} <= set(values)
    assert set(discovery_sources.SOURCES) <= set(values)


def test_employer_queued_by_a_new_board_is_not_manual_and_retires(env):
    queue_up(env, "Acme", "https://jobs.lever.co/acme/1", source="arbetsformedlingen")
    run(env, probe=False)
    acme = listed(env)["Acme"]
    assert acme.found_via == "arbetsformedlingen"
    acme.first_seen = "2025-01-01T00:00:00+00:00"
    assert companies.retire_idle([acme], 90, NOW) == [acme]


def test_stored_found_via_of_a_gone_source_still_loads(env):
    items = companies.load(env.profile_dir)
    companies.record(items, "Old", feed=None, status="unresolved", found_via="gonesite", reason="x")
    companies.save(env.profile_dir, items)
    assert companies.load(env.profile_dir)[0].found_via == "gonesite"


# --- #545: one employer cannot hold the run ---------------------------------------------------------

@pytest.mark.real_robots
@responses.activate
def test_an_employer_that_keeps_follow_waiting_past_its_budget_is_an_error_and_the_run_goes_on(env, monkeypatch):
    """Sander's host asks 20 s between requests and its checks make many: past `EMPLOYER_BUDGET_S` follow gives up
    on that employer (an error row) instead of waiting out every pause, and checks the next one."""
    import types

    from door.scrapers import http_client

    clock = [0.0]
    monkeypatch.setattr(http_client, "time", types.SimpleNamespace(
        monotonic=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s)))
    responses.add(responses.GET, "https://slow.example/robots.txt", body="User-agent: *\nCrawl-delay: 20\n")
    responses.add(responses.GET, re.compile(r"https://slow\.example/.*"), body="x")
    monkeypatch.setattr(follow, "EMPLOYER_BUDGET_S", 100.0)
    asked = []

    def classify(session, company, seen, ctx):
        asked.append(company["company"])
        if company["company"] == "Sander":
            for i in range(50):  # 50 pauses of 20 s: 1000 s without a budget
                session.get(f"https://slow.example/{i}")
        return None

    monkeypatch.setattr(companies_cmd, "_classify", classify)
    queue_up(env, "Sander", "https://www.linkedin.com/jobs/view/1")
    queue_up(env, "Other", "https://www.linkedin.com/jobs/view/2")
    block = run(env, dry_run=True)
    assert sorted(asked) == ["Other", "Sander"]
    assert [e["company"] for e in block["errors"]] == ["Sander"]
    assert "budget" in block["errors"][0]["error"]
    assert clock[0] <= 100.0 + 20.0
