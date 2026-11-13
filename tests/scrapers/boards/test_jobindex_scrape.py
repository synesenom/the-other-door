"""Fixture tests for the full Jobindex scrape() path (C3, fixture layer).

HTTP is mocked with `responses` from payloads captured live under
fixtures/jobindex/ (search pages + detail pages), trimmed to what the parser
reads and with their ad text rewritten (#367); titles, companies, ids, dates
and page structure are the captured ones. One fixture (search_baddate.html)
is a result with its `firstdate` field tampered to exercise the malformed-date
branch. No network.

Captured tids:
  h1673146  Københavns Lufthavne A/S — Jobindex-hosted (read-more-container)
  h1673246  JN Data A/S             — external listing (falls back to teaser)
  h1672945  DANISH CROWN A/S        — used for the detail-error -> teaser path
"""

import json
import re
from pathlib import Path

import pytest
import responses

from door.core.models import JobPosting
from door.scrapers import drain_answered, drain_errors
from door.scrapers.boards import jobindex

_FIX = Path(__file__).parent / "fixtures" / "jobindex"
# Any search URL: all of Denmark (`/jobsoegning?q=…`) or one area (`/jobsoegning/<area>?q=…`).
_SEARCH = re.compile(re.escape(jobindex._SEARCH_URL) + r"(/[a-z0-9-]+){0,2}(\?.*)?$")


def _with_hits(html: str, hitcount: int, page_size: int = 20) -> str:
    """A captured search page claiming *hitcount* hits (the captures predate the field)."""
    return html.replace('{"searchResponse": {', '{"searchResponse": {"hitcount": %d, "page_size": %d, ' % (hitcount, page_size), 1)


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """The scraper sleeps between requests via PoliteSession; skip that in tests."""
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_maps_paginates_and_dedups():
    # Page 1 (30 hits): h1673146, h1673246. Page 2: h1673146 again (cross-page duplicate
    # -> dropped) + h1672945. Page 3: empty -> stop.
    responses.add(responses.GET, _SEARCH, body=_with_hits(_fx("search_page1.html"), 30),
                  content_type="text/html; charset=utf-8")
    responses.add(responses.GET, _SEARCH, body=_fx("search_page2.html"),
                  content_type="text/html; charset=utf-8")
    responses.add(responses.GET, _SEARCH, body=_fx("search_empty.html"),
                  content_type="text/html; charset=utf-8")
    # h1673146 detail has a read-more-container; h1673246 detail lacks one
    # (-> teaser); h1672945 detail errors (-> teaser).
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1673146"),
                  body=_fx("detail_h1673146.html"), content_type="text/html; charset=utf-8")
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1673246"),
                  body=_fx("detail_h1673246.html"), content_type="text/html; charset=utf-8")
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1672945"), status=500)

    postings = jobindex.scrape({"role_targets": ["data scientist"], "location": "Copenhagen"})

    # Cross-page duplicate removed; order preserved.
    assert [p["platform_id"] for p in postings] == ["h1673146", "h1673246", "h1672945"]
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "jobindex"
        assert p["title"] and p["company"] and p["url"] and p["description"]

    by_id = {p["platform_id"]: p for p in postings}

    # Jobindex-hosted: description comes from the detail read-more-container,
    # so it is long and distinct from the short search teaser.
    h146 = by_id["h1673146"]
    assert h146["title"] == "Data Scientist"
    assert h146["company"] == "Københavns Lufthavne A/S"
    assert h146["location"] == "Kastrup"
    assert h146["url"] == "https://www.jobindex.dk/vis-job/h1673146"
    assert h146["id"] == "jobindex.h1673146"
    assert h146["posted_at"].startswith("2026-06-09")
    assert len(h146["description"]) > 1000  # full container text, not the teaser

    # External listing: no container -> description falls back to the teaser.
    h246 = by_id["h1673246"]
    assert h246["company"] == "JN Data A/S"
    assert h246["url"] == "https://www.jobindex.dk/vis-job/h1673246"
    assert h246["location"].startswith("Silkeborg")
    assert h246["posted_at"].startswith("2026-06-10")
    assert h246["description"].startswith("Domain Architect - Datacenter Connectivity")

    # Detail request failed -> teaser fallback still yields a description.
    h945 = by_id["h1672945"]
    assert h945["company"] == "DANISH CROWN A/S"
    assert h945["description"].startswith("Logistics Data Lead")


@responses.activate
def test_scrape_malformed_firstdate_yields_none():
    # search_baddate.html is a real result with firstdate set to a bad value.
    responses.add(responses.GET, _SEARCH, body=_fx("search_baddate.html"),
                  content_type="text/html; charset=utf-8")
    responses.add(responses.GET, _SEARCH, body=_fx("search_empty.html"),
                  content_type="text/html; charset=utf-8")
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1673246"), status=500)

    postings = jobindex.scrape({"role_targets": ["data scientist"], "location": "Copenhagen"})
    assert len(postings) == 1
    assert postings[0]["platform_id"] == "h1673246"
    assert postings[0]["posted_at"] is None


@responses.activate
def test_scrape_search_error_returns_empty():
    # A failing search request is swallowed (printed + break) -> no postings.
    responses.add(responses.GET, _SEARCH, status=500)

    drain_errors()
    postings = jobindex.scrape({"role_targets": ["data scientist"], "location": "Copenhagen"})
    assert postings == []

    errors = drain_errors()
    assert "jobindex" in errors
    assert any("search error" in msg for msg in errors["jobindex"])


@responses.activate
def test_search_error_is_reported_and_recorded(progress_events, capsys):
    responses.add(responses.GET, _SEARCH, status=500)

    drain_errors()
    jobindex.scrape({"role_targets": ["data scientist"], "location": "Copenhagen"})

    assert any("search error (role='data scientist', page=1)" in e.message for e in progress_events)
    assert any("search error" in m for m in drain_errors()["jobindex"])
    assert capsys.readouterr().out == ""


@responses.activate
def test_no_results_block_is_reported_and_recorded(progress_events):
    responses.add(responses.GET, _SEARCH, body="<html>no stash payload</html>",
                  content_type="text/html; charset=utf-8")

    drain_errors()
    jobindex.scrape({"role_targets": ["nothing"], "location": "remote"})

    assert any("no search results block" in e.message for e in progress_events)
    assert any("no search results block" in m for m in drain_errors()["jobindex"])


@responses.activate
def test_iter_scrape_reports_keyword_count_and_detail_progress_without_tqdm(progress_events, capsys):
    responses.add(responses.GET, _SEARCH, body=_fx("search_page1.html"),
                  content_type="text/html; charset=utf-8")
    responses.add(responses.GET, _SEARCH, body=_fx("search_empty.html"),
                  content_type="text/html; charset=utf-8")
    for tid in ("h1673146", "h1673246"):
        responses.add(responses.GET, jobindex._DETAIL_URL.format(tid=tid),
                      body=_fx(f"detail_{tid}.html"), content_type="text/html; charset=utf-8")

    postings = jobindex.scrape({"role_targets": ["data scientist"], "location": "Copenhagen"})

    n = len(postings)
    assert n == 2
    assert any(e.message == "'data scientist': 2 results" and e.site == "jobindex" for e in progress_events)
    # which keyword it searches, of how many, and which ad of the keyword's it reads: structured, for the display
    searching = [e for e in progress_events if e.stage == "keyword_search"]
    assert [(e.message, e.done, e.total) for e in searching] == [("data scientist", 1, 1)]
    details = [e for e in progress_events if e.stage == "ad_details"]
    assert [(e.message, e.done, e.total) for e in details] == [("data scientist", 1, n), ("data scientist", 2, n)]
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
    assert "tqdm" not in Path(jobindex.__file__).read_text()


@responses.activate
def test_scrape_no_stash_returns_empty_and_records_error():
    """A search page without a results block is a format change, not a quiet day:
    it must be recorded so `_scrape_core` reports the site as failed."""
    responses.add(responses.GET, _SEARCH,
                  body="<html>no stash payload</html>",
                  content_type="text/html; charset=utf-8")

    drain_errors()
    drain_answered("jobindex")
    postings = jobindex.scrape({"role_targets": ["nothing"], "location": "remote"})
    assert postings == []
    assert drain_answered("jobindex") is False

    errors = drain_errors()
    assert "jobindex" in errors
    assert any("no search results block" in msg for msg in errors["jobindex"])


@responses.activate
def test_scrape_empty_results_records_no_error():
    """A well-formed page with zero hits is a genuinely quiet search."""
    responses.add(responses.GET, _SEARCH, body=_fx("search_empty.html"),
                  content_type="text/html; charset=utf-8")

    drain_errors()
    drain_answered("jobindex")
    assert jobindex.scrape({"role_targets": ["nothing"], "location": "remote"}) == []
    assert drain_errors() == {}
    assert drain_answered("jobindex") is True


@responses.activate
def test_scrape_reads_result_app_list_key():
    """Live page captured Oct 2026, after Jobindex renamed the Stash key to
    ``jobsearch/result_app/list`` (trimmed to two results)."""
    responses.add(responses.GET, _SEARCH, body=_fx("search_result_app_list.html"),
                  content_type="text/html; charset=utf-8")
    responses.add(responses.GET, _SEARCH, body=_fx("search_empty.html"),
                  content_type="text/html; charset=utf-8")
    for tid in ("h1705017", "h1705712"):
        responses.add(responses.GET, jobindex._DETAIL_URL.format(tid=tid), status=500)

    postings = jobindex.scrape({"role_targets": ["data scientist"], "location": "Copenhagen"})

    assert [p["platform_id"] for p in postings] == ["h1705017", "h1705712"]
    first = postings[0]
    JobPosting.model_validate(first)
    assert first["title"] == "Scientist"
    assert first["company"] == "Xellia Pharmaceuticals ApS"
    assert first["location"] == "København S"
    assert first["url"] == "https://www.jobindex.dk/vis-job/h1705017"
    assert first["posted_at"].startswith("2026-10-06")


@responses.activate
def test_scrape_searches_the_area_as_a_path_segment():
    """robots.txt disallows `geoareaid`; the area path segment is allowed."""
    responses.add(responses.GET, _SEARCH, body=_fx("search_empty.html"),
                  content_type="text/html; charset=utf-8")

    jobindex.scrape({"role_targets": ["data scientist"], "location": "Copenhagen"})

    assert responses.calls[0].request.url == jobindex._SEARCH_URL + "/storkoebenhavn?q=%22data+scientist%22"


@responses.activate
def test_scrape_nationwide_searches_with_the_query_alone():
    responses.add(responses.GET, _SEARCH, body=_fx("search_empty.html"),
                  content_type="text/html; charset=utf-8")

    jobindex.scrape({"role_targets": ["data scientist"], "location": "Denmark"})

    assert responses.calls[0].request.url == jobindex._SEARCH_URL + "?q=%22data+scientist%22"


# --------------------------------------------------------------------------- #
# search_keywords preference over role_targets
# --------------------------------------------------------------------------- #

def test_scrape_uses_search_keywords_over_role_targets(monkeypatch):
    """When search_keywords present, scrape() uses them instead of role_targets."""
    called_with = []

    def fake_search_page(session, query, area, page, category=""):
        called_with.append(query)
        return jobindex._Page(0, 20, [])

    monkeypatch.setattr(jobindex, "_search_page", fake_search_page)

    jobindex.scrape({
        "role_targets": ["lead data scientist"],
        "search_keywords": ["data science lead", "head of data science"],
        "location": "Copenhagen",
    })

    assert called_with == ["data science"]  # both reduce to the same phrase


def test_scrape_falls_back_to_role_targets_when_search_keywords_empty(monkeypatch):
    """When search_keywords is an empty list, scrape() falls back to role_targets."""
    called_with = []

    def fake_search_page(session, query, area, page, category=""):
        called_with.append(query)
        return jobindex._Page(0, 20, [])

    monkeypatch.setattr(jobindex, "_search_page", fake_search_page)

    jobindex.scrape({
        "role_targets": ["lead data scientist"],
        "search_keywords": [],
        "location": "Copenhagen",
    })

    assert called_with == ["data scientist"]


# --------------------------------------------------------------------------- #
# known_ids skip + iter_scrape (issue #134)
#
# `known_ids` is the set of platform_ids the caller (`_scrape_core`) already
# has recorded in `jobs/history.json` and doesn't need a fresh description
# for. For those tids, `scrape`/`iter_scrape` skip `_fetch_detail`
# entirely and yield a lightweight `{"platform_id": tid, "seen_only": True}`
# record instead of a full JobPosting dict.
# --------------------------------------------------------------------------- #

@responses.activate
def test_scrape_skips_detail_fetch_for_known_ids():
    responses.add(responses.GET, _SEARCH, body=_fx("search_page1.html"),
                  content_type="text/html; charset=utf-8")
    responses.add(responses.GET, _SEARCH, body=_fx("search_empty.html"),
                  content_type="text/html; charset=utf-8")
    # Only h1673246 should get a detail request; h1673146 is "known".
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1673246"),
                  body=_fx("detail_h1673246.html"), content_type="text/html; charset=utf-8")

    postings = jobindex.scrape(
        {"role_targets": ["data scientist", "domain architect"], "location": "Copenhagen"},
        known_ids=frozenset({"h1673146"}),
    )

    detail_calls = [c for c in responses.calls if "/jobannonce/" in c.request.url]
    assert len(detail_calls) == 1
    assert "h1673146" not in detail_calls[0].request.url

    by_id = {p["platform_id"]: p for p in postings}
    assert by_id["h1673146"] == {"platform_id": "h1673146", "seen_only": True}
    # The non-known tid is still a full posting.
    assert by_id["h1673246"]["title"]
    assert "seen_only" not in by_id["h1673246"]


@responses.activate
def test_iter_scrape_yields_incrementally():
    """`next()` on the generator returns the first posting after only the
    requests needed for it, not the whole search+detail run."""
    responses.add(responses.GET, _SEARCH, body=_with_hits(_fx("search_page1.html"), 2),
                  content_type="text/html; charset=utf-8")
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1673146"),
                  body=_fx("detail_h1673146.html"), content_type="text/html; charset=utf-8")
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1673246"),
                  body=_fx("detail_h1673246.html"), content_type="text/html; charset=utf-8")

    gen = jobindex.iter_scrape({
        "role_targets": ["data scientist"], "location": "Copenhagen",
        "max_pages_per_keyword": 1,
    })
    first = next(gen)

    assert first["platform_id"] == "h1673146"
    # Only page 1's search request + h1673146's detail request should have
    # fired so far — not the second page or h1673246's detail page.
    urls = [c.request.url for c in responses.calls]
    assert not any("h1673246" in u for u in urls)
    assert len([u for u in urls if "/jobsoegning" in u]) == 1


def test_scrape_respects_max_pages_per_keyword_config(monkeypatch):
    """max_pages_per_keyword in config overrides the default _MAX_PAGES."""
    calls = []

    def fake_search_page(session, query, area, page, category=""):
        calls.append(page)
        return jobindex._Page(0, 20, [])

    monkeypatch.setattr(jobindex, "_search_page", fake_search_page)

    jobindex.scrape({
        "role_targets": ["data scientist"],
        "location": "Copenhagen",
        "max_pages_per_keyword": 1,
    })

    assert calls == [1]


# --------------------------------------------------------------------------- #
# probe (issue #178)
# --------------------------------------------------------------------------- #

_PROBE_CFG = {"role_targets": ["data scientist"], "location": "Copenhagen"}


@responses.activate
def test_probe_ok_on_current_page_shape():
    body = _fx("search_page1.html")
    responses.add(responses.GET, _SEARCH, body=body, content_type="text/html; charset=utf-8")
    drain_errors()
    result = jobindex.probe(_PROBE_CFG)
    assert result["structure_ok"] is True and result["ext"] == "html"
    assert result["raw"] == body
    assert len(result["postings"]) >= 1
    for p in result["postings"]:
        JobPosting.model_validate(p)
    assert len(responses.calls) == 1  # page 1 only, no detail fetches
    assert drain_errors() == {}


@responses.activate
def test_probe_drift_when_results_block_is_gone():
    responses.add(responses.GET, _SEARCH, body=_fx("search_drift.html"),
                  content_type="text/html; charset=utf-8")
    drain_errors()
    result = jobindex.probe(_PROBE_CFG)
    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")
    assert drain_errors() == {}


@responses.activate
def test_probe_empty_but_well_formed_page_is_ok():
    responses.add(responses.GET, _SEARCH, body=_fx("search_empty.html"),
                  content_type="text/html; charset=utf-8")
    result = jobindex.probe(_PROBE_CFG)
    assert result["structure_ok"] is True and result["postings"] == []


@responses.activate
def test_scrape_sends_no_age_filter():
    """robots.txt disallows `jobage`, so the cutoff is applied by `scrape` afterwards."""
    from datetime import datetime, timedelta, timezone

    responses.add(responses.GET, _SEARCH, body=_fx("search_empty.html"))
    since = datetime.now(timezone.utc) - timedelta(days=13)

    assert jobindex.scrape({"role_targets": ["ML Lead"], "location": "Copenhagen"}, since=since) == []
    assert "jobage" not in responses.calls[0].request.url


# --------------------------------------------------------------------------- #
# robots.txt, read for real (issue #226)
# --------------------------------------------------------------------------- #

_ROBOTS = (Path(__file__).parents[1] / "fixtures" / "robots" / "jobindex.txt").read_text(encoding="utf-8")


@pytest.mark.usefixtures("obey_robots")
@pytest.mark.real_robots
@responses.activate
def test_only_the_first_page_is_requested_because_robots_disallows_paging():
    responses.add(responses.GET, "https://www.jobindex.dk/robots.txt", body=_ROBOTS)
    responses.add(responses.GET, _SEARCH, body=_with_hits(_fx("search_page1.html"), 30))
    responses.add(responses.GET, re.compile(r"https://www\.jobindex\.dk/jobannonce/"), body=_fx("detail_h1673146.html"))
    responses.add(responses.GET, re.compile(re.escape(jobindex._SEARCH_URL) + r"/[a-z0-9-]+/[a-z0-9-]+\?.*"),
                  body=_fx("search_empty.html"))

    drain_errors()
    postings = jobindex.scrape({"role_targets": ["data scientist"], "location": "Copenhagen"})

    searches = [c.request.url for c in responses.calls if "/jobsoegning" in c.request.url]
    assert searches[0] == jobindex._SEARCH_URL + "/storkoebenhavn?q=%22data+scientist%22"
    assert not any("page=" in u for u in searches)  # the 30 hits are split instead
    assert postings and drain_errors() == {}


@pytest.mark.real_robots
@responses.activate
def test_a_long_keyword_is_reduced_so_robots_never_blocks_it():
    """Jobindex disallows a query with two '+' (three words or more): "head of data"
    is searched as "data", and nothing disallowed is requested or recorded."""
    responses.add(responses.GET, "https://www.jobindex.dk/robots.txt", body=_ROBOTS)
    responses.add(responses.GET, _SEARCH, body=_fx("search_empty.html"))

    drain_errors()
    jobindex.scrape({"role_targets": ["head of data", "Head of Lead Manager"], "location": "Denmark"})

    searches = [c.request.url for c in responses.calls if "/jobsoegning" in c.request.url]
    assert searches == [jobindex._SEARCH_URL + "?q=data"]
    assert drain_errors() == {}


@pytest.mark.usefixtures("obey_robots")
@pytest.mark.real_robots
@responses.activate
def test_an_employer_page_robots_disallows_is_not_read_but_is_where_to_apply():
    responses.add(responses.GET, "https://www.jobindex.dk/robots.txt", body=_ROBOTS)
    responses.add(responses.GET, "https://ms.recruiting.mindkey-app.com/robots.txt", body="User-agent: *\nDisallow: /\n")
    responses.add(responses.GET, _SEARCH, body=_fx("search_page1.html"))
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1673146"),
                  status=302, headers={"Location": _EMPLOYER_URL})
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1673246"), body=_fx("detail_h1673246.html"))

    drain_errors()
    by_id = {p["platform_id"]: p for p in jobindex.scrape({"role_targets": ["data scientist"], "location": "Denmark"})}

    ad = by_id["h1673146"]
    assert ad["apply_url"] == _EMPLOYER_URL and ad["apply_type"] == "external"
    assert ad["description"].startswith("Data Scientist")  # the teaser
    assert not any(c.request.url == _EMPLOYER_URL for c in responses.calls)
    assert "robots.txt disallows" in drain_errors()["jobindex"][0]


@pytest.mark.real_robots
@responses.activate
def test_further_pages_are_read_when_robots_is_not_obeyed():
    """With robots.txt not obeyed (the default), a search with more hits
    than a page reads on with `page=` before splitting."""
    responses.add(responses.GET, "https://www.jobindex.dk/robots.txt", body=_ROBOTS)
    responses.add(responses.GET, _SEARCH, body=_with_hits(_fx("search_page1.html"), 30))
    responses.add(responses.GET, re.compile(r"https://www\.jobindex\.dk/jobannonce/"), body=_fx("detail_h1673146.html"))

    drain_errors()
    jobindex.scrape({"role_targets": ["data scientist"], "location": "Copenhagen"})

    searches = [c.request.url for c in responses.calls if "/jobsoegning" in c.request.url]
    assert jobindex._SEARCH_URL + "/storkoebenhavn?q=%22data+scientist%22&page=2" in searches


@pytest.mark.real_robots
@responses.activate
def test_an_employer_page_robots_disallows_is_read_when_robots_is_not_obeyed():
    responses.add(responses.GET, "https://www.jobindex.dk/robots.txt", body=_ROBOTS)
    responses.add(responses.GET, "https://ms.recruiting.mindkey-app.com/robots.txt", body="User-agent: *\nDisallow: /\n")
    responses.add(responses.GET, _SEARCH, body=_fx("search_page1.html"))
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1673146"),
                  status=302, headers={"Location": _EMPLOYER_URL})
    responses.add(responses.GET, _EMPLOYER_URL, body=_fx("detail_h1673146.html"))
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1673246"), body=_fx("detail_h1673246.html"))

    drain_errors()
    jobindex.scrape({"role_targets": ["data scientist"], "location": "Denmark"})

    assert any(c.request.url == _EMPLOYER_URL for c in responses.calls)
    assert "robots.txt disallows" not in " ".join(drain_errors().get("jobindex", []))


# --------------------------------------------------------------------------- #
# Ads that redirect to the employer's own page
# --------------------------------------------------------------------------- #

_EMPLOYER_URL = "https://ms.recruiting.mindkey-app.com/en-US/vacancy/230926"


def _redirecting_scrape(employer_body: str) -> dict:
    """Scrape page 1 with h1673146's detail redirecting to the employer page; return that posting."""
    responses.add(responses.GET, _SEARCH, body=_fx("search_page1.html"),
                  content_type="text/html; charset=utf-8")
    responses.add(responses.GET, _SEARCH, body=_fx("search_empty.html"),
                  content_type="text/html; charset=utf-8")
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1673146"),
                  status=302, headers={"Location": _EMPLOYER_URL})
    responses.add(responses.GET, _EMPLOYER_URL, body=employer_body, content_type="text/html; charset=utf-8")
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1673246"),
                  body=_fx("detail_h1673246.html"), content_type="text/html; charset=utf-8")
    postings = jobindex.scrape({"role_targets": ["data scientist"], "location": "Copenhagen"})
    return {p["platform_id"]: p for p in postings}


@responses.activate
def test_employer_page_without_json_ld_gives_its_main_text_and_apply_link():
    # Real Mindkey page: no JobPosting JSON-LD, the ad is the page's <main>.
    by_id = _redirecting_scrape(_fx("employer_mindkey_main.html"))

    ad = by_id["h1673146"]
    assert ad["description"].startswith("Team Lead, Resourcing & Impact")
    assert len(ad["description"]) > 5000
    assert ad["apply_type"] == "external"
    assert ad["apply_url"] == _EMPLOYER_URL
    # Hosted on Jobindex: no employer page, so no apply link.
    assert by_id["h1673246"]["apply_url"] is None


@responses.activate
def test_employer_page_with_only_page_chrome_keeps_the_teaser():
    # Real Coop page: the ad is rendered by JavaScript, so once menus and the
    # cookie banner are dropped next to nothing is left; the teaser is better.
    by_id = _redirecting_scrape(_fx("employer_coop_main.html"))

    ad = by_id["h1673146"]
    assert "cookie" not in ad["description"].lower()
    assert ad["description"].startswith("Data Scientist")  # the search teaser
    assert ad["apply_url"] == _EMPLOYER_URL  # the employer page is still where to apply


_HRM_APPLY = "https://candidate.hr-manager.net/ApplicationInit.aspx?cid=1202&ProjectId=144266&DepartmentId=19128&MediaId=4630"


def _redirect_to(employer_url: str, *mocks) -> dict:
    responses.add(responses.GET, _SEARCH, body=_fx("search_page1.html"),
                  content_type="text/html; charset=utf-8")
    responses.add(responses.GET, _SEARCH, body=_fx("search_empty.html"),
                  content_type="text/html; charset=utf-8")
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1673146"),
                  status=302, headers={"Location": employer_url})
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1673246"),
                  body=_fx("detail_h1673246.html"), content_type="text/html; charset=utf-8")
    for url, body in mocks:
        responses.add(responses.GET, url, body=body, content_type="text/html; charset=utf-8")
    postings = jobindex.scrape({"role_targets": ["data scientist"], "location": "Copenhagen"})
    return {p["platform_id"]: p for p in postings}["h1673146"]


@responses.activate
def test_hr_manager_application_link_gives_its_advertisement():
    ad = _redirect_to(
        _HRM_APPLY,
        (_HRM_APPLY, "<html><body><div>Department is not set or unknown.</div></body></html>"),
        ("https://candidate.hr-manager.net/ApplicationInit.aspx?cid=1202&ProjectId=144266", _fx("hr_manager_ad_144266.html")),
    )
    assert ad["description"].startswith("Machine Learning Engineer")
    assert ad["apply_url"] == _HRM_APPLY


# --------------------------------------------------------------------------- #
# Splitting a full search by category and area (issue #255)
# --------------------------------------------------------------------------- #

_AREA_SITEMAP = jobindex._AREA_SITEMAP_URL
_STORK = jobindex._SEARCH_URL + "/storkoebenhavn"
_CFG = {"search_keywords": ["Lead Data Scientist"], "location": "Copenhagen", "max_pages_per_keyword": 1}
_Q = "?q=%22data+scientist%22"


def _result(n: int) -> dict:
    return {"tid": f"h{n}", "headline": f"Data Scientist {n}", "companytext": f"Firm {n}", "area": "Kastrup",
            "firstdate": "2026-10-10", "share_url": f"https://www.jobindex.dk/vis-job/h{n}", "html": f"<p>Ad {n}</p>"}


def _page(hitcount: int, tids: range, page_size: int = 20) -> str:
    payload = {"jobsearch/result_app/list": {"storeData": {"searchResponse": {
        "hitcount": hitcount, "page_size": page_size, "total_pages": 2,
        "results": [_result(n) for n in tids]}}}}
    return "<html><script>\nvar Stash = " + json.dumps(payload) + ";\n</script></html>"


def _search_mock(url: str, hitcount: int, tids: range) -> None:
    responses.add(responses.GET, url, body=_page(hitcount, tids), content_type="text/html; charset=utf-8")


def _details_fail() -> None:
    responses.add(responses.GET, re.compile(r"https://www\.jobindex\.dk/jobannonce/"), status=500)


def _searches() -> list[str]:
    return [c.request.url for c in responses.calls if "/jobsoegning" in c.request.url]


@responses.activate
def test_a_full_search_is_split_by_category_and_the_union_is_returned():
    _search_mock(_STORK + _Q, 29, range(1, 21))  # top 20 of 29
    _search_mock(f"{jobindex._SEARCH_URL}/handel/storkoebenhavn{_Q}", 14, range(1, 15))
    _search_mock(f"{jobindex._SEARCH_URL}/industri/storkoebenhavn{_Q}", 12, range(10, 22))
    _search_mock(f"{jobindex._SEARCH_URL}/ingenioer/storkoebenhavn{_Q}", 8, range(20, 28))
    _search_mock(f"{jobindex._SEARCH_URL}/it/storkoebenhavn{_Q}", 5, range(26, 30))
    _details_fail()

    drain_errors()
    postings = jobindex.scrape(_CFG)

    assert sorted(int(p["platform_id"][1:]) for p in postings) == list(range(1, 30))  # 29, no duplicate
    assert drain_errors() == {}
    searches = _searches()
    assert searches[0] == _STORK + _Q
    assert all("page=" not in u for u in searches)
    # Stops as soon as the 29 hits are covered: later categories are never asked.
    assert not any("/salg/" in u or "/oevrige/" in u for u in searches)


@responses.activate
def test_a_full_category_is_split_by_sub_area_from_the_area_sitemap():
    _search_mock(_STORK + _Q, 60, range(1, 21))
    _search_mock(f"{jobindex._SEARCH_URL}/it/storkoebenhavn{_Q}", 40, range(1, 21))
    responses.add(responses.GET, _AREA_SITEMAP, body=(_FIX / "area.gz").read_bytes(),
                  content_type="application/x-gzip")
    _search_mock(f"{jobindex._SEARCH_URL}/it/koebenhavn{_Q}", 25, range(21, 41))
    _search_mock(f"{jobindex._SEARCH_URL}/it/frederiksberg{_Q}", 25, range(41, 61))
    # every other search (the other categories, the remaining sub-areas) finds nothing new
    responses.add(responses.GET, re.compile(re.escape(jobindex._SEARCH_URL) + r"/[a-z0-9-]+/[0-9a-z-]+\?.*"),
                  body=_page(0, range(0)))
    _details_fail()

    postings = jobindex.scrape(_CFG)

    assert len(postings) == 60
    assert f"{jobindex._SEARCH_URL}/it/koebenhavn{_Q}" in _searches()
    assert sum(1 for c in responses.calls if c.request.url == _AREA_SITEMAP) == 1  # fetched once


@responses.activate
def test_a_search_still_over_a_page_at_the_narrowest_level_reports_the_shortfall(progress_events):
    _search_mock(_STORK + _Q, 90, range(1, 21))
    responses.add(responses.GET, re.compile(re.escape(jobindex._SEARCH_URL) + r"/[a-z0-9-]+/[0-9a-z-]+\?.*"),
                  body=_page(90, range(1, 21)))
    responses.add(responses.GET, _AREA_SITEMAP, body=(_FIX / "area.gz").read_bytes())
    _details_fail()

    drain_errors()
    postings = jobindex.scrape(_CFG)

    assert len(postings) == 20
    assert drain_errors() == {}  # a shortfall is not an error: the site stays ok
    assert any("70" in e.message and "data scientist" in e.message and "more than" in e.message
               for e in progress_events)


@responses.activate
def test_a_keyword_that_cannot_be_reduced_is_skipped_with_a_report(progress_events):
    responses.add(responses.GET, _SEARCH, body=_fx("search_empty.html"))

    drain_errors()
    assert jobindex.scrape({"search_keywords": ["Head of Lead Manager"], "location": "Copenhagen"}) == []

    assert _searches() == []
    assert drain_errors() == {}
    assert any("Head of Lead Manager" in e.message and "skipped" in e.message for e in progress_events)


@responses.activate
def test_the_request_count_is_reported(progress_events):
    _search_mock(_STORK + _Q, 3, range(1, 4))
    _details_fail()

    jobindex.scrape(_CFG)

    assert any(e.message == "1 search request" for e in progress_events)


@responses.activate
def test_the_same_search_is_fetched_once_for_two_keywords():
    _search_mock(_STORK + _Q, 3, range(1, 4))
    _details_fail()

    jobindex.scrape({"search_keywords": ["data scientist", "principal data scientist"], "location": "Copenhagen"})

    assert _searches() == [_STORK + _Q]


@responses.activate
def test_a_failing_sub_search_is_recorded_and_the_rest_continues():
    _search_mock(_STORK + _Q, 29, range(1, 21))
    responses.add(responses.GET, f"{jobindex._SEARCH_URL}/it/storkoebenhavn{_Q}", status=500)
    _search_mock(f"{jobindex._SEARCH_URL}/ingenioer/storkoebenhavn{_Q}", 9, range(21, 30))
    _details_fail()

    drain_errors()
    postings = jobindex.scrape(_CFG)

    assert len(postings) == 29
    assert any("search error" in m for m in drain_errors()["jobindex"])


@responses.activate
def test_only_on_topic_titles_get_a_detail_request_the_rest_keep_their_teaser():
    """A detail request costs one or more fetches (Jobindex, then often the employer's page);
    a hit whose title shares no word with the keywords is kept with its search teaser instead."""
    responses.add(responses.GET, _SEARCH, body=_fx("search_page1.html"), content_type="text/html; charset=utf-8")
    responses.add(responses.GET, _SEARCH, body=_fx("search_empty.html"), content_type="text/html; charset=utf-8")
    responses.add(responses.GET, jobindex._DETAIL_URL.format(tid="h1673146"),
                  body=_fx("detail_h1673146.html"), content_type="text/html; charset=utf-8")

    postings = jobindex.scrape({"role_targets": ["data scientist"], "location": "Copenhagen"})

    detail_calls = [c.request.url for c in responses.calls if "/jobannonce/" in c.request.url]
    assert len(detail_calls) == 1 and "h1673146" in detail_calls[0]  # "Data Scientist" only
    by_id = {p["platform_id"]: p for p in postings}
    off = by_id["h1673246"]  # "Domain Architect - Datacenter Connectivity"
    assert off["title"].startswith("Domain Architect") and off["description"]  # the teaser


def test_jobindex_pauses_like_the_employer_feeds():
    from door.scrapers import http_client

    assert (jobindex._MIN_DELAY, jobindex._MAX_DELAY) == http_client.FEED_DELAY
