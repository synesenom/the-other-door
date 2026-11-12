"""Fixture tests for the full EURAXESS scrape() path (issue #431): two saved Danish listing pages (trimmed, the
text rewritten, one offer made up for a physics postdoc) and one job page. HTTP is mocked; no network."""

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_pushback
from door.scrapers.boards import euraxess

_FIX = Path(__file__).parent / "fixtures" / "euraxess"
_SEARCH = "https://euraxess.ec.europa.eu/jobs/search"
_CFG = {"search_keywords": ["postdoc physics"], "topic_terms": ["physics", "postdoc", "professor"],
        "location": "Copenhagen, Denmark"}


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr(euraxess.time, "sleep", lambda *a, **k: None)


def _mock_pages():
    responses.add(responses.GET, _SEARCH, body=_html("search_dk_page1.html"),
                  match=[responses.matchers.query_param_matcher({"f[0]": "job_country:757", "sort[name]": "created",
                                                                 "sort[direction]": "DESC"})])
    responses.add(responses.GET, _SEARCH, body=_html("search_dk_page2.html"),
                  match=[responses.matchers.query_param_matcher({"f[0]": "job_country:757", "sort[name]": "created",
                                                                 "sort[direction]": "DESC", "page": "1"})])
    responses.add(responses.GET, re.compile(r"https://euraxess\.ec\.europa\.eu/jobs/\d+"), body=_html("job_476999.html"))


@responses.activate
def test_scrape_keeps_the_offers_on_topic_by_title_or_research_field_and_reads_their_pages():
    _mock_pages()

    postings = euraxess.scrape(_CFG)

    assert [p["platform_id"] for p in postings] == ["476999", "475660"]   # the physics postdoc; the tenure-track professor
    first = postings[0]
    JobPosting.model_validate(first)
    assert (first["id"], first["source"]) == ("euraxess.476999", "euraxess")
    assert first["title"] == "Postdoc in Quantum Optics" and first["company"] == "University of Copenhagen"
    assert first["location"] == "Copenhagen, Denmark" and first["posted_at"].startswith("2026-10-30")
    assert first["url"] == "https://euraxess.ec.europa.eu/jobs/476999"
    assert "trapped atoms" in first["description"] and "Physics" in first["description"]
    assert [c.request.url.split("/jobs/")[1] for c in responses.calls if re.search(r"/jobs/\d+", c.request.url)] == ["476999", "475660"]


@responses.activate
def test_a_known_offer_costs_no_job_page_request():
    _mock_pages()

    postings = euraxess.scrape(_CFG, frozenset({"476999"}))

    assert [p["platform_id"] for p in postings] == ["475660"]


@responses.activate
def test_the_cutoff_stops_the_paging_and_drops_older_offers():
    _mock_pages()
    since = datetime(2026, 10, 28, tzinfo=timezone.utc)

    postings = euraxess.scrape({"location": "Copenhagen, Denmark"}, since=since)

    assert {p["platform_id"] for p in postings} == {"476999", "476522", "476205"}
    assert not any("page=1" in c.request.url for c in responses.calls)


@responses.activate
def test_a_failed_listing_is_a_recorded_error_and_the_rest_stays():
    drain_errors()
    responses.add(responses.GET, _SEARCH, status=500)

    assert euraxess.scrape(_CFG) == []
    assert drain_errors()["euraxess"]


@responses.activate
def test_the_countrys_facet_is_the_profiles(monkeypatch):
    responses.add(responses.GET, _SEARCH, body="<html><body>No results have been found</body></html>")

    euraxess.scrape({**_CFG, "location": "Budapest, Hungary"})

    assert "job_country%3A748" in responses.calls[0].request.url


@responses.activate
def test_a_profile_in_france_reads_frances_list():
    responses.add(responses.GET, _SEARCH, body="<html><body>No results have been found</body></html>")

    euraxess.scrape({**_CFG, "location": "Paris, France"})

    assert "job_country%3A793" in responses.calls[0].request.url


@responses.activate
def test_a_profile_in_sweden_reads_swedens_list():
    responses.add(responses.GET, _SEARCH, body="<html><body>No results have been found</body></html>")

    euraxess.scrape({**_CFG, "location": "Stockholm, Sweden"})

    assert "job_country%3A770" in responses.calls[0].request.url


@responses.activate
def test_probe_reads_page_one_only():
    responses.add(responses.GET, _SEARCH, body=_html("search_dk_page1.html"))

    result = euraxess.probe(_CFG)

    assert result is not None and result["structure_ok"] and len(result["postings"]) == 4
    assert len(responses.calls) == 1


_JOB = re.compile(r"https://euraxess\.ec\.europa\.eu/jobs/\d+")
_PAGE0 = {"f[0]": "job_country:757", "sort[name]": "created", "sort[direction]": "DESC"}


def _listing(status, body="", page=0, headers=None):
    params = dict(_PAGE0, **({"page": str(page)} if page else {}))
    responses.add(responses.GET, _SEARCH, body=body, status=status, headers=headers or {},
                  match=[responses.matchers.query_param_matcher(params)])


@responses.activate
def test_a_429_on_a_listing_page_is_waited_out_once_and_retried(monkeypatch):
    waits = []
    monkeypatch.setattr(euraxess.time, "sleep", waits.append)
    _listing(429, headers={"Retry-After": "7"})
    _listing(200, _html("search_dk_page1.html"))
    _listing(200, _html("search_dk_page2.html"), page=1)
    responses.add(responses.GET, _JOB, body=_html("job_476999.html"))
    drain_pushback("euraxess")

    postings = euraxess.scrape(_CFG)

    assert [p["platform_id"] for p in postings] == ["476999", "475660"]
    assert 7 in waits
    assert drain_pushback("euraxess") is False


@responses.activate
def test_two_429s_in_a_row_stop_the_run_as_pushback_not_an_error():
    _listing(200, _html("search_dk_page1.html"))
    _listing(429, page=1)
    responses.add(responses.GET, _JOB, body=_html("job_476999.html"))
    drain_errors("euraxess")
    drain_pushback("euraxess")

    postings = euraxess.scrape(_CFG)

    assert [p["platform_id"] for p in postings] == ["476999", "475660"]
    assert drain_pushback("euraxess") is True
    assert not drain_errors("euraxess")


@responses.activate
def test_a_429_on_a_job_page_stops_the_run_as_pushback():
    _listing(200, _html("search_dk_page1.html"))
    responses.add(responses.GET, _JOB, status=429)
    drain_pushback("euraxess")

    postings = euraxess.scrape(_CFG)

    assert postings == []
    assert drain_pushback("euraxess") is True
    assert len([c for c in responses.calls if re.search(r"/jobs/\d+", c.request.url)]) == 2   # tried, retried once, then stopped


@responses.activate
def test_only_the_profiles_country_is_kept_and_a_foreign_card_costs_no_job_page():
    # EURAXESS has ignored the country facet before (2026-11) and listed the newest offers worldwide.
    from door.scrapers import drain_non_local
    drain_non_local("euraxess")
    responses.add(responses.GET, _SEARCH, body=_html("search_mixed_page1.html"),
                  match=[responses.matchers.query_param_matcher(_PAGE0)])
    responses.add(responses.GET, _SEARCH, body="<html><body>No results have been found</body></html>",
                  match=[responses.matchers.query_param_matcher(dict(_PAGE0, page="1"))])
    responses.add(responses.GET, _JOB, body=_html("job_476999.html"))

    postings = euraxess.scrape(_CFG)

    assert [p["platform_id"] for p in postings] == ["476999"]
    assert [c.request.url for c in responses.calls if re.search(r"/jobs/\d+", c.request.url)] == [
        "https://euraxess.ec.europa.eu/jobs/476999"]
    assert drain_non_local("euraxess") == 3


@responses.activate
def test_an_older_foreign_card_still_stops_the_paging():
    # The list is worldwide and newest first: a card past the cutoff ends it, whatever its country.
    page0 = {"f[0]": "job_country:770", "sort[name]": "created", "sort[direction]": "DESC"}
    responses.add(responses.GET, _SEARCH, body=_html("search_mixed_page1.html"),
                  match=[responses.matchers.query_param_matcher(page0)])
    responses.add(responses.GET, _SEARCH, body="<html><body>No results have been found</body></html>",
                  match=[responses.matchers.query_param_matcher(dict(page0, page="1"))])

    postings = euraxess.scrape({"location": "Stockholm, Sweden"}, since=datetime(2026, 10, 31, tzinfo=timezone.utc))

    assert postings == []
    assert not any("page=1" in c.request.url for c in responses.calls)
