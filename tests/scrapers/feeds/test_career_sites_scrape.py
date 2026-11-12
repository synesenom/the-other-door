"""Fixture tests for career sites read through sitemaps and JobPosting markup (issue #232).

The Publicis Sapient files follow real ones (robots.txt, a trimmed job sitemap, a job
page cut to its JSON-LD with the description rewritten); the small site `careers.acme.dk` is made up to cover a sitemap index,
`lastmod`, a page without markup, the page cap and a bot challenge.
"""

import re
from datetime import datetime, timezone

import pytest
import responses

from door.core.models import JobPosting
from door.scrapers import drain_entry_errors, drain_errors
from door.scrapers.feeds import career_sites
from paths import TESTS_DIR

# Every test serves the sites' robots.txt itself (career_sites starts from its Sitemap: lines).
pytestmark = pytest.mark.real_robots

_FIX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "career_sites"
_PS = "https://careers.publicissapient.com"
_ACME = "https://careers.acme.dk"


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


def _job_page(title: str, posted: str = "2026-10-05") -> str:
    return f"""<html><head><title>{title}</title>
    <script type="application/ld+json">{{"@context": "https://schema.org", "@type": "JobPosting",
      "title": "{title}", "description": "<p>Build &amp; ship <b>models</b>.</p>", "datePosted": "{posted}",
      "hiringOrganization": {{"@type": "Organization", "name": "Acme A/S"}},
      "jobLocation": {{"@type": "Place", "address": {{"addressLocality": "København", "addressCountry": "DK"}}}},
      "identifier": {{"@type": "PropertyValue", "value": "R-{len(title)}"}}}}</script></head><body></body></html>"""


def _acme(n_jobs: int = 2, robots: str | None = None):
    responses.add(responses.GET, f"{_ACME}/robots.txt", body=robots or f"User-agent: *\nDisallow: /admin\nSitemap: {_ACME}/sitemap_index.xml\n")
    responses.add(responses.GET, f"{_ACME}/sitemap_index.xml", body=f"""<?xml version="1.0"?>
      <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <sitemap><loc>{_ACME}/pages.xml</loc></sitemap><sitemap><loc>{_ACME}/job-sitemap.xml</loc></sitemap>
      </sitemapindex>""")
    urls = "".join(f"<url><loc>{_ACME}/jobs/{i}</loc><lastmod>2026-10-0{i}</lastmod></url>" for i in range(1, n_jobs + 1))
    urls += f"<url><loc>{_ACME}/jobs/old</loc><lastmod>2026-01-01</lastmod></url>"
    responses.add(responses.GET, f"{_ACME}/job-sitemap.xml",
                  body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    for i in range(1, n_jobs + 1):
        responses.add(responses.GET, f"{_ACME}/jobs/{i}", body=_job_page(f"Data Scientist {i}"))
    responses.add(responses.GET, f"{_ACME}/jobs/old", body=_job_page("Old", "2026-01-01"))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_publicis_sapient_from_robots_sitemap_to_posting():
    responses.add(responses.GET, f"{_PS}/robots.txt", body=_fx("ps_robots.txt"))
    responses.add(responses.GET, f"{_PS}/sitemap.xml", body='<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://careers.publicissapient.com/about</loc></url></urlset>')
    responses.add(responses.GET, f"{_PS}/careersJobDetailSitemap.xml", body=_fx("ps_jobs_sitemap.xml"))
    responses.add(responses.GET, re.compile(re.escape(f"{_PS}/job-details/2026-146394")), body=_fx("ps_job_copenhagen.html"))
    responses.add(responses.GET, re.compile(re.escape(f"{_PS}/job-details/2024-")), status=404)

    drain_errors()
    postings = career_sites.scrape({"career_sites": ["careers.publicissapient.com"]})

    [posting] = postings
    JobPosting.model_validate(posting)
    assert posting["title"] == "Data Science - Manager - Retail"
    assert posting["company"] == "Publicis Sapient"
    assert posting["location"] == "Vermundsgade 40 A Copenhagen 2100 Denmark"
    assert posting["posted_at"].startswith("2026-04-08")
    assert posting["description"].startswith("As a Manager for Data Science consulting")
    assert "\\x26" not in posting["description"]  # the JavaScript escapes were decoded
    assert posting["url"].startswith(f"{_PS}/job-details/2026-146394")
    assert posting["source"] == "career_sites"


@responses.activate
def test_a_sitemap_index_is_walked_and_old_pages_are_left_alone():
    _acme()

    postings = career_sites.scrape({"career_sites": [_ACME]}, since=datetime(2026, 9, 1, tzinfo=timezone.utc))

    assert [p["title"] for p in postings] == ["Data Scientist 2", "Data Scientist 1"]  # newest first
    first = postings[0]
    assert first["company"] == "Acme A/S" and first["location"] == "København, DK"
    assert first["description"] == "Build & ship models ."
    assert not any(c.request.url.endswith("/jobs/old") for c in responses.calls)
    assert not any(c.request.url.endswith("/pages.xml") for c in responses.calls)  # not a job sitemap


@responses.activate
def test_known_pages_are_not_fetched_again():
    _acme()
    known = frozenset({career_sites._page_id(f"{_ACME}/jobs/1")})

    postings = career_sites.scrape({"career_sites": [_ACME]}, known_ids=known, since=datetime(2026, 9, 1, tzinfo=timezone.utc))

    assert [p["title"] for p in postings] == ["Data Scientist 2"]
    assert not any(c.request.url.endswith("/jobs/1") for c in responses.calls)


@responses.activate
def test_pages_per_site_are_capped(monkeypatch):
    monkeypatch.setattr(career_sites, "_MAX_PAGES", 2)
    _acme(n_jobs=5)

    postings = career_sites.scrape({"career_sites": [_ACME]})

    assert len(postings) == 2


@responses.activate
def test_a_page_without_markup_is_reported_once_not_failed(progress_events):
    _acme()
    responses.replace(responses.GET, f"{_ACME}/jobs/1", body="<html><body>No markup</body></html>")

    drain_errors()
    postings = career_sites.scrape({"career_sites": [_ACME]}, since=datetime(2026, 9, 1, tzinfo=timezone.utc))

    assert [p["title"] for p in postings] == ["Data Scientist 2"]
    assert drain_errors() == {}
    assert sum("no JobPosting markup" in e.message for e in progress_events) == 1


@responses.activate
def test_a_bot_challenge_stops_the_site_with_a_reason_and_no_retry():
    _acme()
    responses.replace(responses.GET, f"{_ACME}/jobs/2", status=403, body="<title>Just a moment...</title>",
                      headers={"cf-mitigated": "challenge"})

    drain_errors()
    assert career_sites.scrape({"career_sites": [_ACME]}, since=datetime(2026, 9, 1, tzinfo=timezone.utc)) == []

    [error] = drain_errors()["career_sites"]
    assert "bot protection; not attempted" in error
    entry_error = drain_entry_errors("career_sites")[_ACME]  # the employer is named, for `companies list` (#437)
    assert entry_error["outcome"] == "blocked" and "bot protection" in entry_error["reason"]
    assert not any(c.request.url.endswith("/jobs/1") for c in responses.calls)
    assert sum(c.request.url.endswith("/jobs/2") for c in responses.calls) == 1


@responses.activate
def test_without_a_sitemap_line_the_root_sitemap_is_read():
    responses.add(responses.GET, f"{_ACME}/robots.txt", body="User-agent: *\nDisallow:\n")
    responses.add(responses.GET, f"{_ACME}/sitemap.xml",
                  body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{_ACME}/jobs/1</loc></url></urlset>')
    responses.add(responses.GET, f"{_ACME}/jobs/1", body=_job_page("Data Scientist 1"))

    assert len(career_sites.scrape({"career_sites": [_ACME]})) == 1


@responses.activate
def test_an_oracle_cloud_tenant_is_refused_without_a_request():
    drain_errors()
    assert career_sites.scrape({"career_sites": ["https://efzu.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1"]}) == []

    assert len(responses.calls) == 0
    assert "terms" in drain_errors()["career_sites"][0]


@responses.activate
def test_probe_reads_one_job_page_of_the_first_site():
    _acme()

    result = career_sites.probe({"career_sites": [_ACME, "https://other.example"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 1


@responses.activate
def test_probe_drift_when_job_pages_carry_no_markup():
    _acme()
    responses.replace(responses.GET, f"{_ACME}/jobs/2", body="<html></html>")

    result = career_sites.probe({"career_sites": [_ACME]})

    assert result["structure_ok"] is False and "JobPosting" in result["reason"]


def test_nothing_configured():
    assert career_sites.scrape({}) == []
    assert career_sites.probe({}) is None


def _undated_site(n: int, old_from: int, dated: bool = False):
    """A sitemap listing jobs 1..n in order, with lastmod (job i: 2026-10-i) when `dated`; jobs before `old_from` are old."""
    responses.add(responses.GET, f"{_ACME}/robots.txt", body=f"Sitemap: {_ACME}/jobs.xml\n")
    urls = "".join(f"<url><loc>{_ACME}/jobs/{i}</loc>{f'<lastmod>2026-10-{i:02d}</lastmod>' if dated else ''}</url>" for i in range(1, n + 1))
    responses.add(responses.GET, f"{_ACME}/jobs.xml",
                  body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    for i in range(1, n + 1):
        responses.add(responses.GET, f"{_ACME}/jobs/{i}",
                      body=_job_page(f"Job {i}", "2024-01-01" if i < old_from else "2026-10-05"))


@responses.activate
def test_an_undated_sitemap_is_read_from_its_end():
    """Sitemaps without lastmod usually append new jobs at the end."""
    _undated_site(5, old_from=99)

    assert [p["title"] for p in career_sites.scrape({"career_sites": [_ACME]})][:2] == ["Job 5", "Job 4"]


@responses.activate
def test_a_run_of_old_pages_ends_a_site_ordered_by_lastmod(monkeypatch):
    monkeypatch.setattr(career_sites, "_OLD_RUN", 3)
    _undated_site(20, old_from=18, dated=True)

    postings = career_sites.scrape({"career_sites": [_ACME]}, since=datetime(2026, 9, 1, tzinfo=timezone.utc))

    assert [p["title"] for p in postings][:3] == ["Job 20", "Job 19", "Job 18"]
    fetched = [c.request.url for c in responses.calls if "/jobs/" in c.request.url]
    assert len(fetched) == 6  # three new, then three old in a row


@responses.activate
def test_a_run_of_old_foreign_pages_still_ends_a_site_ordered_by_lastmod(monkeypatch):
    monkeypatch.setattr(career_sites, "_OLD_RUN", 3)
    _undated_site(20, old_from=18, dated=True)
    for i in range(1, 18):  # the old jobs are in London, where the profile's filter drops them
        old = _job_page(f"Job {i}", "2024-01-01").replace('"addressLocality": "København", "addressCountry": "DK"',
                                                         '"addressLocality": "London", "addressCountry": "UK"')
        responses.replace(responses.GET, f"{_ACME}/jobs/{i}", body=old)

    career_sites.scrape({"location": "Budapest, Hungary", "career_sites": [_ACME]}, since=datetime(2026, 9, 1, tzinfo=timezone.utc))

    fetched = [c.request.url for c in responses.calls if "/jobs/" in c.request.url]
    assert len(fetched) == 6


@responses.activate
def test_a_page_without_a_declared_charset_is_read_as_utf8():
    """Workday serves its job pages as `text/html` with no charset; requests would guess Latin-1."""
    _acme(n_jobs=1)
    page = _job_page("Fachkraft für Lagerlogistik").encode("utf-8")
    responses.replace(responses.GET, f"{_ACME}/jobs/1", body=page, content_type="text/html")

    [posting] = career_sites.scrape({"career_sites": [_ACME]}, since=datetime(2026, 9, 1, tzinfo=timezone.utc))

    assert posting["title"] == "Fachkraft für Lagerlogistik"


@responses.activate
def test_a_workday_tenant_is_read_from_the_sitemaps_its_robots_txt_lists():
    tenant, site = "https://velux.wd3.myworkdayjobs.com", "https://wd3.myworkdaysite.com/recruiting/velux/Velux_Commercial"
    responses.add(responses.GET, f"{tenant}/robots.txt", body=f"Sitemap: {site}/siteMap.xml\n\nUser-agent: *\nAllow: /Velux_Commercial/\n")
    responses.add(responses.GET, "https://wd3.myworkdaysite.com/robots.txt", status=422)
    responses.add(responses.GET, f"{site}/siteMap.xml",
                  body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{site}/job/Hørsholm/Engineer_R1</loc></url></urlset>')
    responses.add(responses.GET, re.compile(re.escape(f"{site}/job/")), body=_job_page("Engineer"))

    [posting] = career_sites.scrape({"career_sites": [f"{tenant}/Velux_Commercial"]})

    assert posting["title"] == "Engineer" and posting["url"].startswith(f"{site}/job/")


_VX_TENANT = "https://velux.wd3.myworkdayjobs.com"
_VX_SITES = "https://wd3.myworkdaysite.com/recruiting/velux"
_VX_WANTED = "Head-of-Data---AI-Platforms_R1070976"
_THIRTY_DAYS = datetime(2026, 9, 12, tzinfo=timezone.utc)


def _velux_site():
    """The real VELUX Workday sitemaps (no lastmod); every page is a year old except the wanted ad."""
    responses.add(responses.GET, f"{_VX_TENANT}/robots.txt",
                  body=f"Sitemap: {_VX_SITES}/Velux_Commercial/siteMap.xml\nSitemap: {_VX_SITES}/Velux_Residential/siteMap.xml\n")
    responses.add(responses.GET, "https://wd3.myworkdaysite.com/robots.txt", status=422)
    responses.add(responses.GET, f"{_VX_SITES}/Velux_Commercial/siteMap.xml", body=_fx("velux_commercial_sitemap.xml"))
    responses.add(responses.GET, f"{_VX_SITES}/Velux_Residential/siteMap.xml", body=_fx("velux_residential_sitemap.xml"))

    def page(request):
        wanted = request.url.endswith(_VX_WANTED)
        title = "Head of Data & AI Platforms" if wanted else f"Old {request.url.rsplit('/', 1)[-1]}"
        return 200, {"Content-Type": "text/html; charset=utf-8"}, _job_page(title, "2026-10-08" if wanted else "2025-01-01")

    responses.add_callback(responses.GET, re.compile(re.escape(_VX_SITES) + r"/Velux_\w+/job/"), callback=page)


@responses.activate
def test_a_run_of_old_pages_does_not_end_an_undated_sitemap():
    """VELUX (issue #257): Workday sitemaps carry no lastmod, so their order says nothing about age; ten old
    pages in a row must not hide the new ones further down the list."""
    _velux_site()

    postings = career_sites.scrape({"career_sites": [f"{_VX_TENANT}/Velux_Residential"]}, since=_THIRTY_DAYS)

    assert "Head of Data & AI Platforms" in [p["title"] for p in postings]


_DK = {"location": "Copenhagen", "role_targets": ["Data Scientist"]}


@responses.activate
def test_the_cap_keeps_the_local_and_on_topic_pages_of_a_worldwide_employer(monkeypatch, progress_events):
    """VELUX (issue #257): the ad in Hørsholm is entry ~50 of the list; with the cap at 12 it is still read,
    and the run says how many pages were ranked first and how many the cap cut."""
    monkeypatch.setattr(career_sites, "_MAX_PAGES", 12)
    _velux_site()

    postings = career_sites.scrape({**_DK, "career_sites": [f"{_VX_TENANT}/Velux_Residential"]}, since=_THIRTY_DAYS)

    assert "Head of Data & AI Platforms" in [p["title"] for p in postings]
    fetched = [c.request.url for c in responses.calls if "/job/" in c.request.url]
    assert len(fetched) == 12 and all(("Hrsholm" in u or "Data" in u) for u in fetched[:3])
    assert any("ranked first" in e.message and "cut by" in e.message for e in progress_events)


@responses.activate
def test_publicis_sapient_ad_past_the_cap_is_read_because_it_names_copenhagen(monkeypatch):
    monkeypatch.setattr(career_sites, "_MAX_PAGES", 2)
    responses.add(responses.GET, f"{_PS}/robots.txt", body=f"Sitemap: {_PS}/careersJobDetailSitemap.xml\n")
    responses.add(responses.GET, f"{_PS}/careersJobDetailSitemap.xml", body=_fx("ps_world_sitemap.xml"))
    responses.add(responses.GET, re.compile(re.escape(f"{_PS}/job-details/2026-146394")), body=_fx("ps_job_copenhagen.html"))
    responses.add(responses.GET, re.compile(re.escape(f"{_PS}/job-details/")), status=404)

    postings = career_sites.scrape({"location": "Copenhagen", "role_targets": ["Chef"], "career_sites": ["careers.publicissapient.com"]})

    assert "Data Science - Manager - Retail" in [p["title"] for p in postings]


@responses.activate
def test_a_local_on_topic_ad_beats_the_worldwide_on_topic_ones_under_the_cap(monkeypatch):
    """Realistic keywords match 14 of the fixture's worldwide URLs; the cap of 4 still reaches the Copenhagen data-science ad."""
    monkeypatch.setattr(career_sites, "_MAX_PAGES", 4)
    responses.add(responses.GET, f"{_PS}/robots.txt", body=f"Sitemap: {_PS}/careersJobDetailSitemap.xml\n")
    responses.add(responses.GET, f"{_PS}/careersJobDetailSitemap.xml", body=_fx("ps_world_sitemap.xml"))
    responses.add(responses.GET, re.compile(re.escape(f"{_PS}/job-details/2026-146394")), body=_fx("ps_job_copenhagen.html"))
    responses.add(responses.GET, re.compile(re.escape(f"{_PS}/job-details/")), status=404)
    config = {"location": "Copenhagen", "role_targets": ["Data Scientist"], "career_sites": ["careers.publicissapient.com"],
              "search_keywords": ["Lead Data Scientist", "Head of Data Science", "Machine Learning Lead"]}

    postings = career_sites.scrape(config)

    assert "Data Science - Manager - Retail" in [p["title"] for p in postings]
    fetched = [c.request.url for c in responses.calls if "/job-details/" in c.request.url]
    assert "copenhagen" in fetched[0] and "copenhagen" in fetched[1]  # both local ads before any worldwide one
