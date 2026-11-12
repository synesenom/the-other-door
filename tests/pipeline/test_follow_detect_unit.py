"""`follow`'s detection on the employers a test run missed (follow v2): HR-Manager customers from their
application links, short links, job boards that are not employers, namesake feeds, careers listings.

HTTP is mocked with `responses`; DNS is patched off by the `_no_dns` fixture of conftest.py.
"""

import re
from datetime import datetime, timezone

import pytest
import responses

from door.core import candidates, companies
from door.pipeline import follow
from paths import TESTS_DIR

NOW = datetime.now(timezone.utc)
_LISTING = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "career_sites" / "listing"
_HR = "https://candidate.hr-manager.net"
_FEED = "https://api.hr-manager.net/JobPortal.svc/{}/PositionList/json/"


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def queue_up(env, name, *links, source="linkedin", titles=("Data Scientist",), **extra):
    queue = candidates.load(env.jobs_dir)
    candidates.add(queue, name, links=list(links), titles=list(titles), source=source, now=NOW, **extra)
    candidates.save(env.jobs_dir, queue)


def run(env, **kw):
    return follow._follow_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir, **kw)


def listed(env):
    return {c.name: c for c in companies.load(env.profile_dir)}


def hr_feed(alias, cid, status=0):
    ad = f"{_HR}/ApplicationInit.aspx?cid={cid}&ProjectId=1&DepartmentId=2&MediaId=5"
    responses.add(responses.GET, _FEED.format(alias),
                  json={"CustomerAlias": alias, "TransactionStatus": {"StatusCode": status},
                        "Items": [{"AdvertisementUrl": ad, "Name": "Nurse"}]})


def hr_link(cid, project=1):
    return f"{_HR}/ApplicationInit.aspx?cid={cid}&ProjectId={project}&DepartmentId=2&MediaId=5&SkipAdvertisement=true"


def nothing_else(*patterns):
    for pattern in patterns:
        responses.add(responses.GET, re.compile(pattern), status=404)


_ANYTHING = r"https?://(?!api\.hr-manager\.net|candidate\.hr-manager\.net).*"


# --- HR-Manager: the customer of an application link ------------------------------------------------

@responses.activate
def test_an_hr_manager_customer_already_followed_is_recorded_on_that_feed_not_added_again(env):
    items = []
    companies.record(items, "Region Hovedstaden", feed=("hr_manager", "regionh"), status="followed", found_via="manual")
    companies.save(env.profile_dir, items)
    hr_feed("regionh", 342)
    queue_up(env, "Herlev og Gentofte Hospital", hr_link(342, 270860))
    queue_up(env, "Frederiksberg Hospital", hr_link(342, 270937))

    block = run(env)

    assert [(r["company"], r["status"], r["platform"], r["entry"]) for r in block["results"]] == \
        [("Herlev og Gentofte Hospital", "followed", "hr_manager", "regionh"),
         ("Frederiksberg Hospital", "followed", "hr_manager", "regionh")]
    [region] = companies.load(env.profile_dir)
    assert region.name == "Region Hovedstaden" and region.aliases == ["Herlev og Gentofte Hospital", "Frederiksberg Hospital"]
    assert "customer 342" in block["results"][0]["evidence"]
    assert not any("ApplicationInit" in c.request.url for c in responses.calls)  # no ad page was read
    assert companies.feed_config(env.profile_dir) == {"hr_manager_aliases": ["regionh"]}
    assert candidates.load(env.jobs_dir) == {}  # and neither is asked about again


@responses.activate
def test_an_hr_manager_customer_is_found_through_the_employer_site_the_ad_page_links(env):
    queue_up(env, "Roskilde Universitet", hr_link(1310, 148313))
    responses.add(responses.GET, re.compile(re.escape(f"{_HR}/ApplicationInit.aspx")),
                  body='<a href="https://forskning.ruc.dk/en/projects/x/">Project</a><a href="https://ruc.dk/en/job/">Jobs at RUC</a>')
    responses.add(responses.GET, "https://ruc.dk/en/job/",
                  body='<a href="https://candidate.hr-manager.net/vacancies/list.aspx?customer=ruc">All jobs</a>')
    hr_feed("ruc", 1310)

    block = run(env)

    assert (block["results"][0]["platform"], block["results"][0]["entry"]) == ("hr_manager", "ruc")
    assert listed(env)["Roskilde Universitet"].feed.id == "ruc"


@responses.activate
def test_an_alias_whose_feed_belongs_to_another_customer_is_not_taken(env):
    queue_up(env, "Roskilde Universitet", hr_link(1310, 148313))
    responses.add(responses.GET, re.compile(re.escape(f"{_HR}/ApplicationInit.aspx")),
                  body='<a href="https://ruc.dk/en/job/">Jobs</a>')
    responses.add(responses.GET, "https://ruc.dk/en/job/",
                  body='<a href="https://candidate.hr-manager.net/vacancies/list.aspx?customer=other">All jobs</a>')
    hr_feed("other", 999)
    nothing_else(_ANYTHING, r"https://api\.hr-manager\.net/.*")

    run(env)

    assert listed(env)["Roskilde Universitet"].status != "followed"


@responses.activate
def test_a_talentech_short_link_is_followed_to_its_hr_manager_customer(env):
    items = []
    companies.record(items, "Statens Rekrutteringsløsning", feed=("hr_manager", "statensrekrutteringsloesning_tr"),
                     status="followed", found_via="manual")
    companies.save(env.profile_dir, items)
    hr_feed("statensrekrutteringsloesning_tr", 3010)
    target = ("https://careersites-api.talentech.io/redirect?ats_job_id=170019&tenant_id=3b0a&original_apply_url="
              "https%3A%2F%2Fcandidate.hr-manager.net%2FApplicationInit.aspx%3Fcid%3D3010%26ProjectId%3D170019")
    responses.add(responses.GET, "https://go.talentech.io/E4oZx", status=302, headers={"Location": target})
    queue_up(env, "Ministeriet for Natur og Dyrevelfærd", "https://go.talentech.io/E4oZx")

    block = run(env)

    assert block["results"][0]["entry"] == "statensrekrutteringsloesning_tr"
    assert [c.request.url for c in responses.calls if "talentech" in c.request.url] == ["https://go.talentech.io/E4oZx"]
    portal = listed(env)["Statens Rekrutteringsløsning"]
    assert portal.aliases == [] and "Ministeriet for Natur og Dyrevelfærd" in portal.evidence


@responses.activate
def test_the_hr_manager_alias_of_a_name_must_have_the_links_customer_number(env):
    queue_up(env, "HK", hr_link(318))
    responses.add(responses.GET, re.compile(re.escape(f"{_HR}/ApplicationInit.aspx")), body="<html>no links</html>")
    hr_feed("hk", 4444)  # an unrelated customer that happens to be called hk
    nothing_else(_ANYTHING)

    run(env)

    assert listed(env)["HK"].status == "unresolved"


# --- links that name no feed, boards that are not employers --------------------------------------------

@responses.activate
def test_a_dalux_style_hr_on_link_is_recorded_unfollowable(env):
    queue_up(env, "Dalux", "https://www.dalux.com/careers/job?hr=show-job/327277&locale=en_US")
    block = run(env, probe=False)
    assert block["unfollowable"][0]["company"] == "Dalux" and "HR-ON" in block["unfollowable"][0]["reason"]
    assert listed(env)["Dalux"].refusal == "must_not"


@responses.activate
def test_a_visma_recruit_apply_link_is_recorded_unfollowable_cant_yet(env):
    queue_up(env, "Alingsås kommun", "https://recruit.visma.com/spa/public/apply?guidAssignment=2b368797-8e2c-4527-bc80-7cc9ac2d9c39")
    block = run(env, probe=False)
    assert block["unfollowable"][0]["company"] == "Alingsås kommun" and "Visma Recruit" in block["unfollowable"][0]["reason"]
    assert listed(env)["Alingsås kommun"].refusal == "cant_yet"


@responses.activate
def test_a_signatur_portal_link_is_followed_on_the_signatur_feed(env):
    queue_up(env, "Helsingør Kommune", "https://portal.signatur.dk/ExtJobs/DefaultHosting/JobApplication.aspx?ClientId=2296&ERId=132159")
    block = run(env, probe=False)
    assert (block["followed"][0]["platform"], block["followed"][0]["entry"]) == ("signatur", "2296")


@responses.activate
def test_an_aggregator_link_with_a_smartrecruiters_string_id_is_followed_to_that_company(env):
    queue_up(env, "IKEA", "https://engradar.com/jobs/smartrecruiters:interikeagroup:744000154654869", source="jobindex")
    block = run(env, probe=False)
    assert (block["followed"][0]["platform"], block["followed"][0]["entry"]) == ("smartrecruiters", "interikeagroup")


@responses.activate
def test_a_name_is_probed_on_smartrecruiters_and_confirmed_like_the_other_feeds(env):
    queue_up(env, "Interikea", "https://www.jobindex.dk/jobannonce/1", source="jobindex", titles=("Data Scientist",))
    responses.add(responses.GET, re.compile(r"https://api\.smartrecruiters\.com/v1/companies/interikea/postings.*"),
                  json={"totalFound": 2, "content": [{"name": "Senior Data Scientist", "location": {"city": "Malmö"}}]})
    nothing_else(_ANYTHING)

    run(env)

    got = listed(env)["Interikea"]
    assert (got.feed.platform, got.feed.id) == ("smartrecruiters", "interikea") and "queued job title" in got.evidence


@responses.activate
def test_a_smartrecruiters_namesake_with_other_jobs_is_not_followed(env):
    queue_up(env, "Interikea", "https://www.jobindex.dk/jobannonce/1", source="jobindex", titles=("Data Scientist",))
    responses.add(responses.GET, re.compile(r"https://api\.smartrecruiters\.com/v1/companies/interikea/postings.*"),
                  json={"totalFound": 1, "content": [{"name": "Welder", "location": {"city": "Austin"}}]})
    nothing_else(_ANYTHING)

    run(env)

    assert listed(env)["Interikea"].status == "unresolved" and "smartrecruiters" in listed(env)["Interikea"].reason.lower()


@responses.activate
def test_a_smartrecruiters_board_with_no_postings_is_no_match(env):
    queue_up(env, "Interikea", "https://www.jobindex.dk/jobannonce/1", source="jobindex")
    responses.add(responses.GET, re.compile(r"https://api\.smartrecruiters\.com/v1/companies/interikea/postings.*"),
                  json={"totalFound": 0, "content": []})
    nothing_else(_ANYTHING)
    run(env)
    assert listed(env)["Interikea"].status == "unresolved"


@responses.activate
def test_a_jobylon_ad_link_follows_the_company_that_posted_it(env):
    """Jobylon is a platform now (#528): an apply link from Jobbsafari or Platsbanken names an ad, and the ad page
    names the company, so the employer is followed by its company number rather than by its job-board link."""
    ad = (TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "jobylon" / "job_393911.html").read_text(encoding="utf-8")
    queue_up(env, "Lyko", "https://emp.jobylon.com/jobs/393911-lyko-butikschef-till-lyko-marieberg/", source="arbetsformedlingen",
             titles=("Butikschef",))
    responses.add(responses.GET, "https://emp.jobylon.com/jobs/393911/", body=ad, content_type="text/html; charset=utf-8")
    nothing_else(_ANYTHING)

    run(env)

    lyko = listed(env)["Lyko"]
    assert (lyko.status, lyko.feed.platform, lyko.feed.id) == ("followed", "jobylon", "2420"), lyko


@responses.activate
@pytest.mark.parametrize("link", [
    "https://join.com/companies/acme/123-engineer", "https://www.studiejobs.dk/job/1",
    "https://frivilligjob.dk/job/1", "https://temp-team.dk/job/1", "https://www.greenhouse.com/", "https://apply.careers.microsoft.com/careers/job/1",
])
def test_a_job_board_page_with_job_markup_is_never_a_career_site(env, link):
    queue_up(env, "Acme", link, source="jobindex")
    responses.add(responses.GET, re.compile(".*"), body='<script type="application/ld+json">{"@type": "JobPosting"}</script>')

    run(env)

    assert listed(env)["Acme"].status == "unresolved"
    assert not any(c.request.url.startswith(link.split("/")[0] + "//" + link.split("/")[2]) for c in responses.calls)


@responses.activate
def test_a_pfa_style_ad_on_a_shared_ats_host_is_not_fetched_for_a_career_site(env):
    link = "https://career2.successfactors.eu/career?career_ns=job_listing&company=pfapensionP&career_job_req_id=15636"
    queue_up(env, "PFA", link)
    nothing_else(_ANYTHING)

    run(env)

    assert not any("successfactors" in c.request.url for c in responses.calls)


# --- a feed found by the name alone must be the employer's ---------------------------------------------

@responses.activate
def test_a_namesake_board_whose_jobs_fit_nothing_queued_is_not_followed(env):
    queue_up(env, "Quantum", "https://www.jobindex.dk/jobannonce/1", source="jobindex", titles=("Engineering Manager",))
    responses.add(responses.GET, re.compile(r"https://api\.ashbyhq\.com/posting-api/job-board/quantum.*"),
                  json={"jobs": [{"title": "Silicon Photonics Engineer", "location": "Boston"}]})
    nothing_else(_ANYTHING)

    block = run(env)

    quantum = listed(env)["Quantum"]
    assert quantum.status == "unresolved" and "ashby" in quantum.reason.lower() and "another company" in quantum.reason
    assert block["unresolved"][0]["company"] == "Quantum"


@responses.activate
def test_a_board_with_a_queued_title_is_followed_and_says_why(env):
    queue_up(env, "Quantum", "https://www.jobindex.dk/jobannonce/1", source="jobindex", titles=("Engineering Manager",))
    responses.add(responses.GET, re.compile(r"https://api\.ashbyhq\.com/posting-api/job-board/quantum.*"),
                  json={"jobs": [{"title": "Engineering Manager", "location": "Boston"}]})
    nothing_else(_ANYTHING)

    run(env)

    assert listed(env)["Quantum"].feed.platform == "ashby" and "queued job title" in listed(env)["Quantum"].evidence


@responses.activate
def test_a_board_with_a_job_in_the_profiles_city_is_followed(env):
    queue_up(env, "Quantum", "https://www.jobindex.dk/jobannonce/1", source="jobindex", titles=("Something Else",))
    responses.add(responses.GET, re.compile(r"https://api\.ashbyhq\.com/posting-api/job-board/quantum.*"),
                  json={"jobs": [{"title": "Designer", "location": "Copenhagen"}]})
    nothing_else(_ANYTHING)

    run(env)

    assert listed(env)["Quantum"].status == "followed" and "copenhagen" in listed(env)["Quantum"].evidence


# --- a careers page that lists its ads as plain links -------------------------------------------------

@responses.activate
def test_a_site_without_a_feed_is_followed_through_its_listing_page(env):
    ad = "https://bechbruun.com/da/karriere/ledige-stillinger/data-scientist-student/"
    queue_up(env, "Bech-Bruun", ad)
    responses.add(responses.GET, ad, body='<html><a href="/da/karriere/ledige-stillinger/">Ledige stillinger</a></html>')
    responses.add(responses.GET, "https://bechbruun.com/da/karriere/ledige-stillinger/",
                  body=(_LISTING / "bechbruun_list.html").read_text(encoding="utf-8"))
    nothing_else(_ANYTHING)

    block = run(env)

    assert (block["followed"][0]["platform"], block["followed"][0]["entry"]) == \
        ("career_sites", "https://bechbruun.com/da/karriere/ledige-stillinger/")
    assert "links" in listed(env)["Bech-Bruun"].evidence


@responses.activate
def test_a_listing_with_one_ad_is_believed_when_it_is_the_ad_that_led_there(env):
    ad = "https://www.aegirinsights.com/careers/head-of-strategy-and-operations"
    queue_up(env, "Aegir Insights", ad)
    responses.add(responses.GET, ad, body='<html><a href="/careers">Careers</a></html>')
    responses.add(responses.GET, "https://www.aegirinsights.com/careers",
                  body='<html><a href="/careers/head-of-strategy-and-operations">Head of Strategy &amp; Operations</a></html>')
    nothing_else(_ANYTHING)

    run(env)

    assert listed(env)["Aegir Insights"].feed.id == "https://www.aegirinsights.com/careers"


@responses.activate
def test_a_platform_found_on_a_later_page_beats_a_listing_found_on_an_earlier_one(env):
    ad = "https://acme.dk/careers/data-scientist"
    queue_up(env, "Acme", ad)
    responses.add(responses.GET, ad, body='<html><a href="/careers">Careers</a></html>')
    responses.add(responses.GET, "https://acme.dk/careers",
                  body=('<a href="/careers/a">A</a><a href="/careers/b">B</a><a href="/careers/data-scientist">C</a>'
                        '<a href="https://acme.recruitee.com/o/x">Apply</a>'))
    for _ in range(2):  # `responses` serves each registration once when a later pattern also matches
        responses.add(responses.GET, "https://acme.recruitee.com/api/offers/", json={"offers": [{"id": 1}]})
    nothing_else(_ANYTHING)

    run(env)

    assert listed(env)["Acme"].status == "followed", listed(env)["Acme"]
    assert listed(env)["Acme"].feed.platform == "recruitee"


# --- the Haiku fallback ----------------------------------------------------------------------------------

def _ai(monkeypatch, url, calls):
    from door.core import careers_ai

    def ask(name, title, location, **kw):
        calls.append((name, title, location))
        return url

    monkeypatch.setattr(careers_ai, "ask_careers_url", ask)


@responses.activate
def test_an_unresolved_employer_is_asked_once_and_a_confirmed_feed_is_followed(env, monkeypatch):
    calls = []
    _ai(monkeypatch, "https://hk.dk/job", calls)
    queue_up(env, "HK", hr_link(318), titles=("Advokatsekretær",))
    responses.add(responses.GET, re.compile(re.escape(f"{_HR}/ApplicationInit.aspx")), body="<html>no links</html>")
    responses.add(responses.GET, "https://hk.dk/job",
                  body='<a href="https://candidate.hr-manager.net/Agent/Subscription.aspx?customer=hkdanmark">Job agent</a>')
    hr_feed("hkdanmark", 318)
    nothing_else(_ANYTHING)

    block = run(env)

    hk = listed(env)["HK"]
    assert (hk.status, hk.feed.id, hk.found_via) == ("followed", "hkdanmark", "ai")
    assert "https://hk.dk/job" in hk.evidence and calls == [("HK", "Advokatsekretær", "Copenhagen")]
    assert block["followed"][0]["entry"] == "hkdanmark"


@responses.activate
def test_an_ai_url_that_confirms_no_feed_follows_nothing(env, monkeypatch):
    _ai(monkeypatch, "https://nowhere.example/careers", [])
    queue_up(env, "Acme", "https://acme.dk/jobs/1")
    nothing_else(_ANYTHING)
    run(env)
    assert listed(env)["Acme"].status == "unresolved"


@responses.activate
def test_the_ai_is_not_asked_when_the_setting_is_off(env, monkeypatch):
    from profile_utils import write_config

    write_config(env.profile_dir, {"location": "Copenhagen", "follow_ai_fallback": False})
    calls = []
    _ai(monkeypatch, "https://acme.dk/careers", calls)
    queue_up(env, "Acme", "https://acme.dk/jobs/1")
    nothing_else(_ANYTHING)
    run(env)
    assert calls == []


@responses.activate
def test_the_ai_is_not_asked_again_within_ninety_days(env, monkeypatch):
    calls = []
    _ai(monkeypatch, None, calls)
    queue_up(env, "Acme", "https://acme.dk/jobs/1")
    nothing_else(_ANYTHING)
    run(env)
    queue_up(env, "Acme", "https://acme.dk/jobs/2")
    run(env)
    assert len(calls) == 1


def test_the_ai_is_not_asked_without_probing(env, monkeypatch):
    calls = []
    _ai(monkeypatch, "https://acme.dk/careers", calls)
    queue_up(env, "Acme", "https://acme.dk/jobs/1")
    run(env, probe=False)
    assert calls == []


@responses.activate
def test_the_ai_questions_run_together_after_every_python_check_is_done(env, monkeypatch):
    import threading

    from door.core import careers_ai

    assert careers_ai.MAX_PARALLEL == 4
    lock = threading.Lock()
    state = {"now": 0, "peak": 0, "calls": 0, "fetched_before_first_call": None}
    gate = threading.Barrier(4, timeout=5)

    def ask(name, title, location, **kw):
        with lock:
            if state["fetched_before_first_call"] is None:
                state["fetched_before_first_call"] = len(responses.calls)
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
            state["calls"] += 1
        try:
            gate.wait()  # four questions are in flight at once, or this times out
        except threading.BrokenBarrierError:
            pass
        with lock:
            state["now"] -= 1
        return None

    monkeypatch.setattr(careers_ai, "ask_careers_url", ask)
    for i in range(8):
        queue_up(env, f"Acme{i}", f"https://acme{i}.dk/jobs/1")
    nothing_else(_ANYTHING)

    block = run(env)

    assert state["calls"] == 8 and 2 <= state["peak"] <= careers_ai.MAX_PARALLEL
    assert state["fetched_before_first_call"] >= 8  # the Python checks of all came first
    assert {c.status for c in companies.load(env.profile_dir)} == {"unresolved"} and block["checked"] == 8


@responses.activate
def test_customer_3010_is_the_state_portal_without_reading_a_page(env):
    queue_up(env, "Trafikstyrelsen", hr_link(3010, 170019))

    block = run(env)

    assert (block["results"][0]["platform"], block["results"][0]["entry"]) == ("hr_manager", "statensrekrutteringsloesning_tr")
    assert "3010" in block["results"][0]["evidence"]
    assert len(responses.calls) == 0
    portal = listed(env)["Statens Rekrutteringsløsning"]
    assert portal.status == "followed" and "Trafikstyrelsen" in portal.evidence


# --- demo tenants and dead feeds are never followed (#435) -------------------------------------------

_FEEDS = TESTS_DIR / "scrapers" / "feeds" / "fixtures"


@responses.activate
def test_a_demo_tenant_found_by_name_is_not_followed_even_with_a_queued_title(env):
    queue_up(env, "Maersk", "https://www.jobindex.dk/jobannonce/1", source="jobindex", titles=("iOS developer",))
    responses.add(responses.GET, "https://maersk.teamtailor.com/jobs.json",
                  body=(_FEEDS / "teamtailor" / "demo_tenant.json").read_text())
    nothing_else(_ANYTHING)

    run(env)

    maersk = listed(env)["Maersk"]
    assert maersk.status == "unresolved" and maersk.feed is None and "demo" in maersk.reason


@responses.activate
def test_a_feed_found_by_name_with_nothing_queued_must_still_have_a_job_in_the_profiles_place(env):
    queue_up(env, "Novo Nordisk", "https://www.jobindex.dk/jobannonce/1", source="jobindex", titles=())
    body = (_FEEDS / "pinpoint" / "demo_tenant.json").read_text().replace("Vape tattooed", "We are")  # no ipsum left
    responses.add(responses.GET, "https://novonordisk.pinpointhq.com/postings.json", body=body)
    nothing_else(_ANYTHING)

    run(env)

    assert listed(env)["Novo Nordisk"].status == "unresolved"


@responses.activate
def test_two_employers_on_feeds_with_the_same_jobs_are_a_shared_demo(env):
    jobs = {"data": [{"title": t, "location": {"name": "Copenhagen"}} for t in ("Head of DEI", "Marketing Manager", "Intern")]}
    for slug in ("novonordisk", "kpmg"):
        responses.add(responses.GET, f"https://{slug}.pinpointhq.com/postings.json", json=jobs)
    queue_up(env, "Novo Nordisk", "https://www.jobindex.dk/jobannonce/1", source="jobindex", titles=())
    queue_up(env, "KPMG", "https://www.jobindex.dk/jobannonce/2", source="jobindex", titles=())
    nothing_else(_ANYTHING)

    run(env)

    got = listed(env)
    assert [got[n].status for n in ("Novo Nordisk", "KPMG")].count("followed") <= 1
    assert "same jobs" in got["KPMG"].reason or "same jobs" in got["Novo Nordisk"].reason


@responses.activate
def test_a_linked_hr_manager_alias_whose_feed_answers_400_is_unresolved(env):
    queue_up(env, "Mellemfolkeligt Samvirke", f"{_HR}/vacancies/list.aspx?customer=MFS")
    responses.add(responses.GET, re.compile(re.escape(_FEED.format("mfs")) + ".*"), status=400,
                  body=(_FEEDS / "hr_manager" / "dead_alias_400.json").read_text())
    nothing_else(_ANYTHING)

    run(env)

    ms = listed(env)["Mellemfolkeligt Samvirke"]
    assert ms.status == "unresolved" and ms.feed is None and "400" in ms.reason
