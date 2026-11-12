"""Career sites of global employers: jobs elsewhere are dropped before any page is fetched.

A Workday job list is asked for the profile's country (the location facets of its first answer, saved
from a real Cisco tenant), a sitemap's URLs are judged by the place names in their path. HTTP is mocked.
"""

import json
import re

import pytest
import responses

from door.scrapers import drain_errors, drain_non_local
from door.scrapers.feeds import career_sites
from paths import TESTS_DIR

pytestmark = pytest.mark.real_robots

_FIX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "career_sites" / "workday"
_BASE = "https://cisco.wd5.myworkdayjobs.com"
_API = f"{_BASE}/wday/cxs/cisco/Cisco_Careers/jobs"
_CPH_ID = "8676de3331b41001f4ea5fef5dcf0000"
_DK = {"location": "Copenhagen, Denmark", "career_sites": [_BASE]}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _fix(name):
    return json.loads((_FIX / name).read_text(encoding="utf-8"))


def _page(title):
    return (f'<html><script type="application/ld+json">{{"@type": "JobPosting", "title": "{title}", "description": "d",'
            f'"datePosted": "2026-10-05", "hiringOrganization": {{"name": "Cisco"}}}}</script></html>')


def _tenant(answers):
    """Mock Cisco's Workday: an empty sitemap, the job list answering by the facets it is asked for."""
    responses.add(responses.GET, f"{_BASE}/robots.txt", body=f"Sitemap: {_BASE}/Cisco_Careers/siteMap.xml\n")
    responses.add(responses.GET, f"{_BASE}/Cisco_Careers/siteMap.xml",
                  body='<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>')
    asked = []

    def cxs(request):
        body = json.loads(request.body)
        asked.append(body)
        key = json.dumps(body["appliedFacets"], sort_keys=True)
        return 200, {"Content-Type": "application/json"}, json.dumps(answers.get(key, {"total": 0, "jobPostings": []}))

    responses.add_callback(responses.POST, _API, callback=cxs)
    responses.add_callback(responses.GET, re.compile(re.escape(_BASE) + r"/Cisco_Careers/job/"),
                           callback=lambda r: (200, {"Content-Type": "text/html; charset=utf-8"}, _page(r.url.rsplit("/", 1)[-1])))
    return asked


@responses.activate
def test_a_workday_job_list_is_asked_for_the_profiles_country_and_the_rest_counted_as_non_local():
    drain_non_local("career_sites")
    asked = _tenant({"{}": _fix("cisco_unfiltered.json"),
                     json.dumps({"locations": [_CPH_ID]}, sort_keys=True): _fix("cisco_copenhagen.json")})

    postings = career_sites.scrape(_DK)

    assert asked[0]["appliedFacets"] == {} and asked[1]["appliedFacets"] == {"locations": [_CPH_ID]}
    assert len(postings) == 3 and all("Armenia" not in p["url"] for p in postings)
    assert any("Copenhagen-Denmark" in p["url"] for p in postings)
    assert drain_non_local("career_sites") == 1392 - 14   # the unfiltered total minus the local jobs
    assert drain_errors("career_sites") == {}


@responses.activate
def test_without_a_known_country_the_job_list_is_read_whole():
    asked = _tenant({"{}": _fix("cisco_unfiltered.json")})
    career_sites.scrape({"location": "Atlantis", "career_sites": [_BASE]})
    assert [a["appliedFacets"] for a in asked][:1] == [{}] and all(a["appliedFacets"] == {} for a in asked)
    assert drain_non_local("career_sites") == 0


@responses.activate
def test_a_tenant_with_no_local_location_reads_no_job_page():
    drain_non_local("career_sites")
    facets = [{"facetParameter": "locationMainGroup", "values": [{"facetParameter": "locations", "descriptor": "Locations",
               "values": [{"descriptor": "Armenia", "id": "a", "count": 5}]}]}]
    _tenant({"{}": {"total": 5, "jobPostings": [{"title": "T", "externalPath": "/job/Armenia/T_1"}], "facets": facets}})

    assert career_sites.scrape(_DK) == []
    assert not any("/job/" in c.request.url for c in responses.calls)
    assert drain_non_local("career_sites") == 5


@responses.activate
def test_sitemap_urls_naming_another_country_are_not_fetched():
    drain_non_local("career_sites")
    site = "https://careers.example.com"
    paths = ["/job/Chicago-Illinois/Data-Scientist_R1", "/job/Copenhagen/Data-Scientist_R2",
             "/job/Ballerup-Denmark/Engineer_R3", "/job/Munich-Germany/Engineer_R4", "/job/Remote/Engineer_R5",
             "/job/Platform-Engineer_R6"]
    urls = "".join(f"<url><loc>{site}{p}</loc></url>" for p in paths)
    responses.add(responses.GET, f"{site}/robots.txt", body=f"Sitemap: {site}/sitemap.xml\n")
    responses.add(responses.GET, f"{site}/sitemap.xml",
                  body=f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    responses.add_callback(responses.GET, re.compile(re.escape(site) + r"/job/"),
                           callback=lambda r: (200, {"Content-Type": "text/html; charset=utf-8"}, _page(r.url.rsplit("/", 1)[-1])))

    postings = career_sites.scrape({"location": "Copenhagen, Denmark", "career_sites": [site]})

    fetched = {c.request.url.rsplit("/", 1)[-1] for c in responses.calls if "/job/" in c.request.url}
    assert fetched == {"Data-Scientist_R2", "Engineer_R3", "Engineer_R5", "Platform-Engineer_R6"}
    assert len(postings) == 4 and drain_non_local("career_sites") == 2


def _located_page(place):
    location = ('"jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": '
                f'"{place[0]}", "addressCountry": "{place[1]}"}}}},' if place else "")
    return ('<html><script type="application/ld+json">{"@type": "JobPosting", "title": "Data Scientist", "description": "d",'
            f'{location} "datePosted": "2026-10-05", "hiringOrganization": {{"name": "Acme"}}}}</script></html>')


@responses.activate
def test_a_job_ad_whose_json_ld_location_is_in_another_country_is_dropped_and_counted():
    drain_non_local("career_sites")
    site = "https://careers.example.com"
    places = {"R1": ("London", "UK"), "R2": ("Budapest", "HU"), "R3": None}
    urls = "".join(f"<url><loc>{site}/job/{k}</loc></url>" for k in places)
    responses.add(responses.GET, f"{site}/robots.txt", body=f"Sitemap: {site}/sitemap.xml\n")
    responses.add(responses.GET, f"{site}/sitemap.xml",
                  body=f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    responses.add_callback(responses.GET, re.compile(re.escape(site) + r"/job/"),
                           callback=lambda r: (200, {"Content-Type": "text/html; charset=utf-8"},
                                               _located_page(places[r.url.rsplit("/", 1)[-1]])))

    postings = career_sites.scrape({"location": "Budapest, Hungary", "career_sites": [site]})

    assert sorted(p["url"].rsplit("/", 1)[-1] for p in postings) == ["R2", "R3"]
    assert drain_non_local("career_sites") == 1


def _requirement_page(country):
    requirement = (f'"applicantLocationRequirements": {{"@type": "Country", "name": "{country}"}},' if country else "")
    return ('<html><script type="application/ld+json">{"@type": "JobPosting", "title": "Data Scientist", "description": "d",'
            f'{requirement} "datePosted": "2026-10-05", "hiringOrganization": {{"name": "Acme"}}}}</script></html>')


@responses.activate
def test_a_job_ad_with_only_a_foreign_applicant_location_requirement_is_dropped_and_counted():
    drain_non_local("career_sites")
    site = "https://careers.example.com"
    countries = {"R1": "Germany", "R2": "Hungary", "R3": None}
    urls = "".join(f"<url><loc>{site}/job/{k}</loc></url>" for k in countries)
    responses.add(responses.GET, f"{site}/robots.txt", body=f"Sitemap: {site}/sitemap.xml\n")
    responses.add(responses.GET, f"{site}/sitemap.xml",
                  body=f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    responses.add_callback(responses.GET, re.compile(re.escape(site) + r"/job/"),
                           callback=lambda r: (200, {"Content-Type": "text/html; charset=utf-8"},
                                               _requirement_page(countries[r.url.rsplit("/", 1)[-1]])))

    postings = career_sites.scrape({"location": "Budapest, Hungary", "career_sites": [site]})

    assert sorted(p["url"].rsplit("/", 1)[-1] for p in postings) == ["R2", "R3"]
    assert drain_non_local("career_sites") == 1
