"""Career sites without a usable sitemap or JobPosting markup (follow v2): a listing page whose ad links
are read, pages built from their text, and Workday's own job list when its sitemap stops at 100 jobs.

The listing and ad pages keep the structure of real ones (trimmed to what is read, their text rewritten):
Bech-Bruun, Signatur (Helsingør Kommune), PFA (SuccessFactors career2 ads linked from pfa.dk), Pentia and
Hansen & Toft (AG Gruppen).
"""

import json
import re
from datetime import datetime, timezone

import pytest
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.feeds import career_sites
from paths import TESTS_DIR

pytestmark = pytest.mark.real_robots

_FIX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "career_sites"
_BB = "https://bechbruun.com"
_BB_LIST = f"{_BB}/da/karriere/ledige-stillinger/"


def _listing(name: str) -> str:
    return (_FIX / "listing" / f"{name}.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _no_sitemap(base):
    responses.add(responses.GET, f"{base}/robots.txt", body="User-agent: *\nDisallow:\n")
    responses.add(responses.GET, f"{base}/sitemap.xml", status=404)


@responses.activate
def test_a_site_without_sitemap_or_markup_is_read_through_its_listing_page():
    _no_sitemap(_BB)
    responses.add(responses.GET, _BB_LIST, body=_listing("bechbruun_list"))
    responses.add(responses.GET, re.compile(re.escape(_BB_LIST) + r"[a-z-]+/"), body=_listing("bechbruun_ad"))

    drain_errors()
    postings = career_sites.scrape({"career_sites": [_BB_LIST]})

    assert len(postings) >= 6  # every ad link answers with the same fixture page
    JobPosting.model_validate(postings[0])
    assert postings[0]["title"] == "Data Scientist student"
    assert len(postings[0]["description"]) > 200 and "Cookie" not in postings[0]["title"]
    assert postings[0]["source"] == "career_sites" and postings[0]["url"].startswith(_BB_LIST)
    assert drain_errors() == {}


@responses.activate
def test_each_ad_of_a_listing_becomes_a_posting_with_its_own_title():
    _no_sitemap(_BB)
    responses.add(responses.GET, _BB_LIST, body=_listing("bechbruun_list"))

    def ad(request):
        slug = request.url.rstrip("/").rsplit("/", 1)[-1]
        page = _listing("bechbruun_ad").replace("Data Scientist student", slug.replace("-", " ").title())
        return 200, {"Content-Type": "text/html; charset=utf-8"}, page

    responses.add_callback(responses.GET, re.compile(re.escape(_BB_LIST) + r"[a-z-]+/"), callback=ad)

    postings = career_sites.scrape({"career_sites": [_BB_LIST]})

    assert len(postings) >= 6 and len({p["title"] for p in postings}) == len(postings)
    assert "Data Scientist Student" in [p["title"] for p in postings]


@responses.activate
def test_a_known_ad_of_a_listing_is_not_fetched_again():
    _no_sitemap(_BB)
    responses.add(responses.GET, _BB_LIST, body=_listing("bechbruun_list"))
    responses.add(responses.GET, re.compile(re.escape(_BB_LIST) + r"[a-z-]+/"), body=_listing("bechbruun_ad"))
    known = frozenset({career_sites._page_id(f"{_BB_LIST}data-scientist-student/")})

    career_sites.scrape({"career_sites": [_BB_LIST]}, known_ids=known)

    assert not any(c.request.url.endswith("/data-scientist-student/") for c in responses.calls)


@responses.activate
def test_a_plain_host_entry_without_a_sitemap_does_not_guess_a_listing():
    _no_sitemap(_BB)

    assert career_sites.scrape({"career_sites": [_BB]}) == []
    assert not any("ledige" in c.request.url for c in responses.calls)


@responses.activate
def test_a_signatur_portal_is_read_through_its_job_list_page():
    portal = "https://portal.signatur.dk"
    listing = f"{portal}/ExtJobs/DefaultHosting/JobList.aspx?ClientId=2296"
    _no_sitemap(portal)
    responses.add(responses.GET, listing, body=_listing("signatur_list"))
    responses.add(responses.GET, re.compile(re.escape(f"{portal}/ExtJobs/DefaultHosting/JobDetails.aspx")), body=_listing("signatur_ad"))

    posting = career_sites.scrape({"career_sites": [listing]})[0]

    assert posting["title"] == "Plejehjemsleder til Plejehjemmet Strandhøj"
    assert posting["url"].startswith(f"{portal}/ExtJobs/DefaultHosting/JobDetails.aspx?ClientId=2296")


@responses.activate
def test_ads_on_another_host_that_carry_a_job_id_are_read_too():
    """pfa.dk links its SuccessFactors career2 ads."""
    listing = "https://www.pfa.dk/om-pfa/job-i-pfa/ledige-job/"
    _no_sitemap("https://www.pfa.dk")
    responses.add(responses.GET, listing, body=_listing("pfa_list"))
    responses.add(responses.GET, re.compile(r"https://career2\.successfactors\.eu/career"), body=_listing("pfa_ad"))
    for host in ("career2.successfactors.eu",):
        responses.add(responses.GET, f"https://{host}/robots.txt", body="User-agent: *\nDisallow:\n")

    postings = career_sites.scrape({"career_sites": [listing]})

    assert postings and "Leder af AI Platform" in postings[0]["title"]
    assert postings[0]["url"].startswith("https://career2.successfactors.eu/career")


@responses.activate
def test_pages_of_a_job_sitemap_without_markup_are_read_from_their_text():
    """job.hansentoft.dk (AG Gruppen): a sitemap of /jobs/<id> pages with no JobPosting markup."""
    base = "https://job.hansentoft.dk"
    responses.add(responses.GET, f"{base}/robots.txt", body=f"Sitemap: {base}/sitemap.xml\n")
    urls = "".join(f"<url><loc>{base}/jobs/{9400 + i}</loc></url>" for i in range(7))
    responses.add(responses.GET, f"{base}/sitemap.xml",
                  body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{base}/</loc></url>{urls}</urlset>')

    def ad(request):
        n = request.url.rsplit("/", 1)[-1]
        return 200, {"Content-Type": "text/html; charset=utf-8"}, _listing("hansentoft_ad").replace("Projekteringsleder", f"Projekteringsleder {n}")

    responses.add_callback(responses.GET, re.compile(re.escape(base) + r"/jobs/\d+"), callback=ad)

    postings = career_sites.scrape({"career_sites": [base]})

    assert len(postings) == 7
    assert all(p["title"].startswith("Projekteringsleder 94") for p in postings)
    assert postings[0]["company"] and "hansentoft" not in postings[0]["title"].lower()


@responses.activate
def test_a_site_with_markup_on_some_pages_never_falls_back_to_text():
    base = "https://careers.acme.dk"
    responses.add(responses.GET, f"{base}/robots.txt", body=f"Sitemap: {base}/sitemap.xml\n")
    urls = "".join(f"<url><loc>{base}/jobs/{i}</loc></url>" for i in range(1, 9))
    responses.add(responses.GET, f"{base}/sitemap.xml",
                  body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    marked = ('<script type="application/ld+json">{"@type": "JobPosting", "title": "Marked", "description": "x"}</script>')
    for i in range(1, 9):
        responses.add(responses.GET, f"{base}/jobs/{i}", body=f"<html><body>{marked if i == 8 else ''}<h1>Page {i}</h1><p>{'text ' * 100}</p></body></html>")

    postings = career_sites.scrape({"career_sites": [base]})

    assert [p["title"] for p in postings] == ["Marked"]


@responses.activate
def test_a_role_page_is_a_job_page_so_puffy_style_sitemaps_work():
    base = "https://careers.puffy.test"
    responses.add(responses.GET, f"{base}/robots.txt", body=f"Sitemap: {base}/sitemap.xml\n")
    responses.add(responses.GET, f"{base}/sitemap.xml",
                  body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{base}/</loc></url>'
                       f'<url><loc>{base}/privacy</loc></url><url><loc>{base}/roles/head-of-ai</loc></url></urlset>')
    ld = '<script type="application/ld+json">{"@type": "JobPosting", "title": "Head of AI", "description": "x"}</script>'
    responses.add(responses.GET, f"{base}/roles/head-of-ai", body=f"<html><body>{ld}</body></html>")

    assert [p["title"] for p in career_sites.scrape({"career_sites": [base]})] == ["Head of AI"]


@responses.activate
def test_pages_of_a_job_sitemap_that_are_people_profiles_are_not_postings():
    """A sitemap of /expertise/<name> pages (no markup, no job word, no apply link) is not a job list."""
    base = "https://www.zeiss.example"
    responses.add(responses.GET, f"{base}/robots.txt", body=f"Sitemap: {base}/sitemap.xml\n")
    urls = "".join(f"<url><loc>{base}/expertise/person-{i}</loc></url>" for i in range(7))
    responses.add(responses.GET, f"{base}/sitemap.xml",
                  body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    responses.add(responses.GET, re.compile(re.escape(base) + r"/expertise/person-\d"), body=_listing("zeiss_profile"))

    assert career_sites.scrape({"career_sites": [base]}) == []


@responses.activate
def test_the_followed_name_wins_for_marked_and_text_pages():
    base = "https://job.hansentoft.dk"
    responses.add(responses.GET, f"{base}/robots.txt", body=f"Sitemap: {base}/sitemap.xml\n")
    urls = "".join(f"<url><loc>{base}/jobs/{9400 + i}</loc></url>" for i in range(4))
    responses.add(responses.GET, f"{base}/sitemap.xml",
                  body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    responses.add(responses.GET, re.compile(re.escape(base) + r"/jobs/\d+"), body=_listing("hansentoft_ad"))

    postings = career_sites.scrape({"career_sites": [f"{base}/"], "_names": {"career_sites": {"job.hansentoft.dk": "Hansen & Toft"}}})

    assert postings and {p["company"] for p in postings} == {"Hansen & Toft"}


@responses.activate
def test_the_followed_name_wins_for_a_listing_entry_and_for_marked_pages():
    base = "https://careers.puffy.test"
    responses.add(responses.GET, f"{base}/robots.txt", body=f"Sitemap: {base}/sitemap.xml\n")
    responses.add(responses.GET, f"{base}/sitemap.xml",
                  body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                       f'<url><loc>{base}/roles/head-of-ai</loc></url></urlset>')
    ld = ('<script type="application/ld+json">{"@type": "JobPosting", "title": "Head of AI", "description": "x",'
          '"hiringOrganization": {"name": "Puffy Legal Ltd"}}</script>')
    responses.add(responses.GET, f"{base}/roles/head-of-ai", body=f"<html><body>{ld}</body></html>")

    postings = career_sites.scrape({"career_sites": [base], "_names": {"career_sites": {"careers.puffy.test": "Puffy"}}})

    assert [p["company"] for p in postings] == ["Puffy"]


# --- Workday: the sitemap stops at 100 jobs, the tenant's own job list does not ---------------------------------

_WD = "https://simcorp.wd3.myworkdayjobs.com"
_NZ = "https://novonesis.wd103.myworkdayjobs.com"


def _workday(total_pages: dict[int, dict], sitemap_paths=()):
    responses.add(responses.GET, f"{_WD}/robots.txt",
                  body=f"Sitemap: {_WD}/SimCorp_Jobs/siteMap.xml\nSitemap: {_WD}/SimCorp_Private/siteMap.xml\n")
    urls = "".join(f"<url><loc>{_WD}/SimCorp_Jobs{p}</loc></url>" for p in sitemap_paths)
    responses.add(responses.GET, f"{_WD}/SimCorp_Jobs/siteMap.xml",
                  body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    responses.add(responses.GET, f"{_WD}/SimCorp_Private/siteMap.xml", body='<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>')
    seen = []

    def cxs(request):
        body = json.loads(request.body)
        seen.append(body)
        return 200, {"Content-Type": "application/json"}, json.dumps(total_pages.get(body["offset"], {"total": 0, "jobPostings": []}))

    responses.add_callback(responses.POST, f"{_WD}/wday/cxs/simcorp/SimCorp_Jobs/jobs", callback=cxs)
    responses.add(responses.POST, f"{_WD}/wday/cxs/simcorp/SimCorp_Private/jobs", json={"total": 0, "jobPostings": []})
    return seen


def _simcorp_jobs():
    return json.loads((_FIX / "workday" / "simcorp_jobs.json").read_text(encoding="utf-8"))["jobPostings"]


def _job_page_for(title):
    return (f'<html><script type="application/ld+json">{{"@type": "JobPosting", "title": "{title}", "description": "d",'
            f'"datePosted": "2026-10-05", "hiringOrganization": {{"name": "SimCorp"}}}}</script></html>')


@responses.activate
def test_a_workday_tenants_own_job_list_adds_the_jobs_its_sitemap_leaves_out():
    jobs = _simcorp_jobs()
    in_sitemap = jobs[1]["externalPath"]
    seen = _workday({0: {"total": 3, "jobPostings": jobs}}, sitemap_paths=[in_sitemap])
    responses.add_callback(responses.GET, re.compile(re.escape(_WD) + r"/SimCorp_Jobs/job/"),
                           callback=lambda r: (200, {"Content-Type": "text/html; charset=utf-8"},
                                               _job_page_for(r.url.rsplit("/", 1)[-1])))

    postings = career_sites.scrape({"career_sites": [_WD]})

    assert len(postings) == 3  # the one from the sitemap and the two only the job list names
    assert any("Director--Transfer-Pricing" in p["url"] for p in postings)
    assert seen == [{"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}]
    assert sum(c.request.url.endswith(in_sitemap) for c in responses.calls) == 1  # read once, not twice


@responses.activate
def test_the_workday_job_list_is_paged_until_its_total():
    jobs = _simcorp_jobs()
    page = lambda n: [{**jobs[0], "externalPath": f"/job/Copenhagen/Role-{n}-{i}_R-{n}{i}"} for i in range(20 if n < 1 else 5)]
    seen = _workday({0: {"total": 25, "jobPostings": page(0)}, 20: {"total": 25, "jobPostings": page(1)}})
    responses.add_callback(responses.GET, re.compile(re.escape(_WD) + r"/SimCorp_Jobs/job/"),
                           callback=lambda r: (200, {"Content-Type": "text/html; charset=utf-8"}, _job_page_for(r.url.rsplit("/", 1)[-1])))

    postings = career_sites.scrape({"career_sites": [_WD]})

    assert [s["offset"] for s in seen] == [0, 20] and len(postings) == 25


@responses.activate
def test_a_workday_job_list_that_fails_leaves_the_sitemap_result_alone():
    jobs = _simcorp_jobs()
    _workday({}, sitemap_paths=[jobs[1]["externalPath"]])
    responses.replace(responses.POST, f"{_WD}/wday/cxs/simcorp/SimCorp_Jobs/jobs", status=500)
    responses.add(responses.GET, re.compile(re.escape(_WD) + r"/SimCorp_Jobs/job/"), body=_job_page_for("Only"))

    assert [p["title"] for p in career_sites.scrape({"career_sites": [_WD]})] == ["Only"]


def test_the_workday_sites_come_from_the_robots_sitemap_lines():
    lines = (f"{_WD}/SimCorp_Jobs/siteMap.xml", f"{_WD}/SimCorp_Private/siteMap.xml",
             "https://wd3.myworkdaysite.com/recruiting/velux/Velux_Commercial/siteMap.xml")
    assert career_sites._workday_sites(lines, _WD) == ["SimCorp_Jobs", "SimCorp_Private"]


def test_without_sitemap_lines_the_workday_sites_come_from_the_robots_disallow_lines():
    """Novonesis: its robots.txt names its sites only in ``Disallow:`` lines (and ``/refreshFacet/``, no site)."""
    disallowed = ("/Novonesis_Careers/", "/Novonesis_Careers_Private/", "/refreshFacet/", "/a/b/", "/")
    assert career_sites._workday_sites((), _NZ, disallowed) == ["Novonesis_Careers", "Novonesis_Careers_Private"]
    assert career_sites._workday_sites((f"{_NZ}/Other/siteMap.xml",), _NZ, disallowed) == ["Other"]


@responses.activate
def test_a_workday_tenant_without_sitemap_lines_is_read_through_its_job_list():
    jobs = _simcorp_jobs()
    responses.add(responses.GET, f"{_NZ}/robots.txt",
                  body="User-agent: *\nDisallow: /Novonesis_Careers/\nDisallow: /refreshFacet/\n")
    responses.add(responses.POST, f"{_NZ}/wday/cxs/novonesis/Novonesis_Careers/jobs", json={"total": 3, "jobPostings": jobs})
    responses.add_callback(responses.GET, re.compile(re.escape(_NZ) + r"/Novonesis_Careers/job/"),
                           callback=lambda r: (200, {"Content-Type": "text/html; charset=utf-8"},
                                               _job_page_for(r.url.rsplit("/", 1)[-1])))

    postings = career_sites.scrape({"career_sites": [_NZ]})

    assert len(postings) == 3


@responses.activate
def test_probe_reads_one_ad_of_a_listing_entry_from_its_text():
    _no_sitemap(_BB)
    responses.add(responses.GET, _BB_LIST, body=_listing("bechbruun_list"))
    responses.add(responses.GET, re.compile(re.escape(_BB_LIST) + r"[a-z-]+/"), body=_listing("bechbruun_ad"))

    result = career_sites.probe({"career_sites": [_BB_LIST]})

    assert result["structure_ok"] is True and result["postings"][0]["title"] == "Data Scientist student"


@responses.activate
def test_a_sitemap_whose_lastmod_is_one_day_for_every_page_does_not_end_the_site(monkeypatch):
    """BCG: every page of the sitemap says it changed today (the day it was generated), so ten old
    postings in a row say nothing about the rest."""
    monkeypatch.setattr(career_sites, "_OLD_RUN", 3)
    base = "https://careers.acme.dk"
    responses.add(responses.GET, f"{base}/robots.txt", body=f"Sitemap: {base}/jobs.xml\n")
    urls = "".join(f"<url><loc>{base}/jobs/{i}</loc><lastmod>2026-10-13T09:11:54+00:00</lastmod></url>" for i in range(1, 11))
    responses.add(responses.GET, f"{base}/jobs.xml", body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    for i in range(1, 11):
        old = i in (10, 9, 8, 7, 6, 5)  # fetched first (newest lastmod order is the reversed listing)
        responses.add(responses.GET, f"{base}/jobs/{i}", body=_job_page_for_date(f"Job {i}", "2025-01-01" if old else "2026-10-05"))

    postings = career_sites.scrape({"career_sites": [base]}, since=datetime(2026, 9, 1, tzinfo=timezone.utc))

    assert {"Job 1", "Job 2", "Job 3", "Job 4"} <= {p["title"] for p in postings}


def _job_page_for_date(title, posted):
    return (f'<html><script type="application/ld+json">{{"@type": "JobPosting", "title": "{title}", "description": "d",'
            f'"datePosted": "{posted}"}}</script></html>')


@responses.activate
def test_a_lastmod_a_little_before_the_cutoff_does_not_hide_a_page():
    """BCG: an ad posted on 5 October carries `lastmod` 10 September; only a page whose lastmod is far
    older than the cutoff is skipped."""
    base = "https://careers.acme.dk"
    responses.add(responses.GET, f"{base}/robots.txt", body=f"Sitemap: {base}/jobs.xml\n")
    rows = {"recent": "2026-10-10", "slightly-old": "2026-08-20", "ancient": "2025-12-01", "other": "2026-10-11"}
    urls = "".join(f"<url><loc>{base}/jobs/{k}</loc><lastmod>{v}</lastmod></url>" for k, v in rows.items())
    responses.add(responses.GET, f"{base}/jobs.xml", body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    for k in rows:
        responses.add(responses.GET, f"{base}/jobs/{k}", body=_job_page_for_date(k, "2026-10-05"))

    titles = {p["title"] for p in career_sites.scrape({"career_sites": [base]}, since=datetime(2026, 9, 13, tzinfo=timezone.utc))}

    assert titles == {"recent", "slightly-old", "other"}
