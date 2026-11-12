"""`follow` finds a named employer's own careers site when no link names its feed (issue #566).

Large Swedish employers queued by a board with a register's name and no usable link ("Telia Sverige AB",
"Hilti Svenska Aktiebolag") found nothing through the name probes. Their website is read from Wikidata, and
its careers pages, the careers hosts of its domain and the Workday tenant named like it are run through the
same detection as any link. Saved real answers in `tests/fixtures/employer_site/` (Wikidata's API, the
careers pages with their text and scripts left out, Telia's Workday robots.txt and job list).
"""

import re
from datetime import datetime, timezone

import pytest
import responses

import wikidata_utils
from door.commands import companies as companies_cmd
from door.core import candidates, companies, wikidata
from door.pipeline import follow
from profile_utils import write_config

NOW = datetime.now(timezone.utc)
_TELIA_WD = "https://teliacompany.wd3.myworkdayjobs.com"


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@pytest.fixture
def sweden(env, monkeypatch):
    """A Stockholm profile; DNS knows the one careers host of H&M's domain."""
    write_config(env.profile_dir, {"role_targets": ["data scientist"], "location": "Stockholm", "languages": ["en"]})
    monkeypatch.setattr(companies_cmd, "_resolves", lambda host: host == "career.hm.com")
    return env


def queue_up(env, *names, source="jobbsafari"):
    queue = candidates.load(env.jobs_dir)
    for name in names:
        candidates.add(queue, name, links=[], titles=["Data Scientist"], source=source, now=NOW)
    candidates.save(env.jobs_dir, queue)


def serve_the_web(**override):
    """Wikidata's saved answers, the saved pages and Telia's Workday tenant; every other page, feed and tenant
    answers 404. *override* maps a URL to the status it answers instead."""
    page = wikidata_utils.text
    pages = {
        "https://www2.hm.com/": (403, ""),     # H&M's own site turns door away
        "https://career.hm.com/": (200, page("career_hm_com.html")),
        "http://www.telia.se/": (200, page("telia_se.html")),
        "https://www.teliacompany.com/sv": (200, page("teliacompany_sv.html")),
        "https://www.hilti.com/": (200, page("hilti_com.html")),
        "https://careers.hilti.group/en": (200, page("careers_hilti_group_en.html")),
        f"{_TELIA_WD}/robots.txt": (200, page("teliacompany_wd3_robots.txt")),
        f"{_TELIA_WD}/wday/cxs/teliacompany/Telia_careers/jobs": (200, page("teliacompany_wd3_jobs.json")),
    }
    pages.update({url: (status, "") for url, status in override.items()})

    def answer(request):
        if wikidata_utils.WIKIDATA_API.fullmatch(request.url):
            return wikidata_utils.answer(request)
        status, body = pages.get(request.url, (404, ""))
        return status, {}, body

    for method in (responses.GET, responses.POST):
        responses.add_callback(method, re.compile(r"https?://.*"), callback=answer)


def rows(block):
    return {r["company"]: (r["status"], r["platform"], r["entry"]) for r in block["results"]}


@pytest.mark.real_robots
@responses.activate
def test_hm_telia_and_hilti_from_a_swedish_queue_are_followed_on_their_own_careers_sites(sweden):
    serve_the_web()
    queue_up(sweden, "H & M Hennes & Mauritz GBC AB", "H & M Hennes & Mauritz Sverige AB", "Telia Sverige AB",
             "Hilti Svenska Aktiebolag")

    block = follow._follow_core(jobs_dir=sweden.jobs_dir, profile_dir=sweden.profile_dir)

    assert rows(block) == {
        "H & M Hennes & Mauritz GBC AB": ("followed", "smartrecruiters", "hmgroup"),
        "H & M Hennes & Mauritz Sverige AB": ("followed", "smartrecruiters", "hmgroup"),
        "Telia Sverige AB": ("followed", "career_sites", f"{_TELIA_WD}/Telia_careers"),
        "Hilti Svenska Aktiebolag": ("followed", "career_sites", "https://careers.hilti.group/en"),
    }
    evidence = {r["company"]: r["evidence"] for r in block["results"]}
    assert evidence["Telia Sverige AB"].startswith("Wikidata Q4567911 (Telia Sverige)")
    assert "career.hm.com" in evidence["H & M Hennes & Mauritz GBC AB"]
    assert "www.hilti.com" in evidence["Hilti Svenska Aktiebolag"]
    followed = {c.name: c for c in companies.load(sweden.profile_dir) if c.status == "followed"}
    assert {(c.feed.platform, c.feed.id) for c in followed.values()} == {
        ("smartrecruiters", "hmgroup"), ("career_sites", f"{_TELIA_WD}/Telia_careers"),
        ("career_sites", "https://careers.hilti.group/en")}
    assert not candidates.load(sweden.jobs_dir)
    searches = [c.request.url for c in responses.calls if "wbsearchentities" in c.request.url]
    assert len(searches) == 6     # H&M's two names are one employer: looked up once


@pytest.mark.real_robots
@responses.activate
def test_an_employer_wikidata_does_not_know_stays_unresolved_with_the_reason(sweden):
    serve_the_web()
    queue_up(sweden, "Nobody Known AB")

    block = follow._follow_core(jobs_dir=sweden.jobs_dir, profile_dir=sweden.profile_dir)

    [row] = block["results"]
    assert row["status"] == "unresolved" and "Wikidata" in row["reason"]


@pytest.mark.real_robots
@responses.activate
def test_a_website_that_shows_no_feed_says_so(sweden):
    """Telia's own sites draw their careers pages by script, and no Workday tenant answers: unresolved, and the
    reason names the website read."""
    serve_the_web(**{f"{_TELIA_WD}/robots.txt": 422})
    queue_up(sweden, "Telia Sverige AB")

    block = follow._follow_core(jobs_dir=sweden.jobs_dir, profile_dir=sweden.profile_dir)

    [row] = block["results"]
    assert row["status"] == "unresolved" and "telia.se" in row["reason"]


@pytest.mark.real_robots
@responses.activate
def test_a_wikidata_that_does_not_answer_is_no_error(sweden):
    responses.add(responses.GET, re.compile(r"https://www\.wikidata\.org/.*"), status=503)
    responses.add(responses.GET, re.compile(r"https?://(?!www\.wikidata\.org/).*"), status=404)
    responses.add(responses.POST, re.compile(r"https?://.*"), status=404)
    queue_up(sweden, "Telia Sverige AB", "Hilti Svenska Aktiebolag")

    block = follow._follow_core(jobs_dir=sweden.jobs_dir, profile_dir=sweden.profile_dir)

    assert not block["errors"]
    assert {r["status"] for r in block["results"]} == {"unresolved"}
    assert all("Wikidata" in r["reason"] for r in block["results"])


@pytest.mark.real_robots
@responses.activate
def test_an_employer_wikidata_was_not_asked_about_waits_in_the_queue_for_a_later_run(sweden, monkeypatch):
    """Wikidata stopped answering: the employers it was not asked about are not recorded as unresolved (which
    settles them for 90 days) and stay queued; one Wikidata knows nothing about is recorded."""
    monkeypatch.setattr(wikidata, "_rest", lambda seconds: None)
    responses.add(responses.GET, re.compile(r"https://www\.wikidata\.org/.*"), status=429)
    responses.add(responses.GET, re.compile(r"https?://(?!www\.wikidata\.org/).*"), status=404)
    responses.add(responses.POST, re.compile(r"https?://.*"), status=404)
    queue_up(sweden, "Telia Sverige AB", "Hilti Svenska Aktiebolag")

    block = follow._follow_core(jobs_dir=sweden.jobs_dir, profile_dir=sweden.profile_dir)

    assert not block["errors"] and block["kept"] == 2
    assert {c["name"] for c in candidates.load(sweden.jobs_dir).values()} == {"Telia Sverige AB", "Hilti Svenska Aktiebolag"}
    assert not companies.load(sweden.profile_dir)


@pytest.mark.real_robots
@responses.activate
def test_an_employer_wikidata_knows_nothing_about_is_recorded_and_dequeued(sweden):
    serve_the_web()
    queue_up(sweden, "Nobody Known AB")

    block = follow._follow_core(jobs_dir=sweden.jobs_dir, profile_dir=sweden.profile_dir)

    assert block["kept"] == 0 and not candidates.load(sweden.jobs_dir)
    assert [c.status for c in companies.load(sweden.profile_dir)] == ["unresolved"]


@pytest.mark.real_robots
@responses.activate
def test_an_employer_with_a_followed_feeds_postings_only_is_not_looked_up(sweden):
    serve_the_web()
    queue_up(sweden, "Telia Sverige AB", source="teamtailor")

    follow._follow_core(jobs_dir=sweden.jobs_dir, profile_dir=sweden.profile_dir)

    assert not any("wikidata" in c.request.url for c in responses.calls)


@pytest.mark.real_robots
@responses.activate
def test_companies_add_by_name_finds_the_employers_own_careers_site_too(sweden):
    serve_the_web()

    [result] = companies_cmd._resolve_core(["Hilti Svenska Aktiebolag"], location="Stockholm")["results"]

    assert (result["platform"], result["entry"]) == ("career_sites", "https://careers.hilti.group/en")


# --- the hosts and tenants tried for a website (pure) ----------------------------------------------------

def test_a_websites_domain_drops_the_labels_that_name_no_employer():
    assert companies_cmd._domain("https://www2.hm.com") == "hm.com"
    assert companies_cmd._domain("https://www.teliacompany.com/sv") == "teliacompany.com"
    assert companies_cmd._domain("https://careers.hilti.group/en") == "hilti.group"
    assert companies_cmd._domain("http://telia.se") == "telia.se"


def test_the_careers_hosts_of_a_domain_include_the_countrys_own_labels():
    hosts = companies_cmd._site_hosts("https://www2.hm.com", companies_cmd._site_labels("Stockholm"))
    assert hosts[:4] == ["careers.hm.com", "career.hm.com", "jobs.hm.com", "job.hm.com"]
    assert "karriar.hm.com" in hosts and "jobb.hm.com" in hosts
    assert "karriar.hm.com" not in companies_cmd._site_hosts("https://www2.hm.com", companies_cmd._site_labels(""))


def test_the_tenants_tried_are_the_names_and_the_domains_of_the_employer_and_its_parent():
    from door.core import wikidata

    group = wikidata.Employer("Q862303", "Telia Company", "https://www.teliacompany.com/sv", True)
    found = wikidata.Employer("Q4567911", "Telia Sverige", "http://www.telia.se", True, group)

    assert companies_cmd._tenant_slugs(found) == ["telia", "teliacompany"]
