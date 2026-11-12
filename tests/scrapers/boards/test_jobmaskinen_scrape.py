"""Fixture tests for the Jobmaskinen scrape() path, with HTTP mocked from saved pages.

`search_page1.html`, `search_page2.html` and `search_last_page.html` are the result blocks of
real searches (`elektriker`, then `manager`), `detail_*.html` the JSON-LD of four ads; the ad text
is rewritten. The site is Danish only (Jobnet's ads), so there is no English ad to keep.
"""

from pathlib import Path

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_answered, drain_errors, drain_pushback
from door.scrapers.boards import jobmaskinen

_FIX = Path(__file__).parent / "fixtures" / "jobmaskinen"
_CFG = {"role_targets": ["elektriker"], "location": "Copenhagen"}


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _serve(url: str, body: str | None = None, **kw) -> None:
    responses.add(responses.GET, url, body=body, **kw)


def _search(keyword: str, page: int, name: str) -> None:
    _serve(jobmaskinen._search_url(keyword, page), _fx(name))


def _detail(job_id: str, name: str | None = None, **kw) -> None:
    _serve(jobmaskinen._job_url(job_id), _fx(name or f"detail_{job_id}.html"), **kw)


def _two_pages() -> None:
    """Page 1 (3 ads, a next link) and page 2 (a repeat of ad 6535434, one new, no next link)."""
    _search("elektriker", 1, "search_page1.html")
    page2 = _fx("search_page2.html")
    repeated = _fx("search_page1.html").split('<div class="aka_opslaaetdato">')[2]
    repeated = '<div class="aka_opslaaetdato">' + repeated.split('<div style="clear:both;"></div>')[0] \
        + '<div style="clear:both;"></div>'
    page2 = page2.replace('<div class="aka_opslaaetdato">', repeated + '<div class="aka_opslaaetdato">', 1)
    page2 = page2.replace('nav_jobright', 'nav_hidden')
    _serve(jobmaskinen._search_url("elektriker", 2), page2)


@responses.activate
def test_scrape_paginates_dedups_and_reads_details():
    _two_pages()
    for job_id in ("6535427", "6535434"):
        _detail(job_id)
    for job_id in ("6535450", "6535654", "6535658", "6535355"):
        _detail(job_id, "detail_6535434.html")

    drain_errors()
    postings = jobmaskinen.scrape(_CFG)

    ids = [p["platform_id"] for p in postings]
    assert ids == ["6535427", "6535434", "6535450", "6535654", "6535658", "6535355"]  # 6535434 once
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "jobmaskinen"
        assert p["title"] and p["company"] and p["url"] and p["description"]
        assert "<" not in p["description"]
    first = postings[0]
    assert first["id"] == "jobmaskinen.6535427"
    assert first["url"] == "https://job.jobmaskinen.dk/jobliste/?jobnet=6535427"
    assert first["company"] == "PowerMatch ApS"
    assert first["location"] == "Odense"
    assert first["posted_at"].startswith("2026-10-29T12:33:53")
    assert drain_errors() == {}
    detail_calls = [c for c in responses.calls if "jobnet=" in c.request.url]
    assert len(detail_calls) == 6  # one per distinct ad


@responses.activate
def test_scrape_skips_detail_for_known_ids():
    _search("elektriker", 1, "search_page1.html")
    _serve(jobmaskinen._search_url("elektriker", 2), _fx("search_last_page.html"))
    _detail("6535434")
    for job_id in ("6535450", "6530742", "6529404"):
        _detail(job_id, "detail_6535434.html")
    _detail("6535427")

    postings = jobmaskinen.scrape(_CFG, known_ids=frozenset({"6535427"}))

    by_id = {p["platform_id"]: p for p in postings}
    assert by_id["6535427"] == {"platform_id": "6535427", "seen_only": True}
    assert by_id["6535434"]["title"]
    assert not any(c.request.url.endswith("jobnet=6535427") for c in responses.calls)


@responses.activate
def test_scrape_old_ads_are_left_alone_when_since_is_given():
    from datetime import datetime, timezone

    _search("elektriker", 1, "search_last_page.html")  # posted 21-10 and 19-10
    _detail("6530742")
    postings = jobmaskinen.scrape(_CFG, since=datetime(2026, 10, 20, tzinfo=timezone.utc))

    assert [p["platform_id"] for p in postings] == ["6530742"]
    assert not any("6529404" in c.request.url for c in responses.calls)


@responses.activate
def test_scrape_failed_detail_keeps_the_card_and_records_the_error():
    _search("elektriker", 1, "search_last_page.html")
    _detail("6530742")
    _serve(jobmaskinen._job_url("6529404"), "boom", status=500)

    drain_errors()
    postings = jobmaskinen.scrape(_CFG)

    by_id = {p["platform_id"]: p for p in postings}
    assert set(by_id) == {"6530742", "6529404"}
    teaser = by_id["6529404"]
    assert teaser["title"] == "Facility Manager til Movia"
    assert teaser["company"] == "Trafikselskabet Movia"
    assert teaser["location"] == "Valby"
    assert teaser["description"]  # the card's job type
    assert any("6529404" in e for e in drain_errors().get("jobmaskinen", []))


@responses.activate
def test_scrape_search_error_is_recorded_not_raised():
    _serve(jobmaskinen._search_url("elektriker", 1), "down", status=500)

    drain_errors()
    assert jobmaskinen.scrape(_CFG) == []
    assert drain_errors()


@responses.activate
@pytest.mark.parametrize("status", [429, 403])
def test_scrape_pushback_is_recorded_and_stops_the_site(status):
    _serve(jobmaskinen._search_url("elektriker", 1), "no", status=status)
    _serve(jobmaskinen._search_url("sygeplejerske", 1), _fx("search_last_page.html"))

    drain_errors()
    drain_pushback("jobmaskinen")
    postings = jobmaskinen.scrape({"search_keywords": ["elektriker", "sygeplejerske"]})

    assert postings == []
    assert drain_pushback("jobmaskinen") is True
    assert drain_errors()
    assert len(responses.calls) <= 4  # the retries of the first request only; the second keyword is not tried


@responses.activate
def test_scrape_zero_hit_page_is_answered_not_an_error():
    _serve(jobmaskinen._search_url("zzzqq", 1), _fx("search_no_results.html"))
    drain_errors()
    drain_answered(jobmaskinen._SITE)
    assert jobmaskinen.scrape({"role_targets": ["zzzqq"]}) == []
    assert drain_errors() == {}
    assert drain_answered(jobmaskinen._SITE) is True


@responses.activate
def test_scrape_unrecognised_page_is_recorded_as_a_change():
    _serve(jobmaskinen._search_url("zzzqq", 1), "<html><body>Ingen job</body></html>")
    drain_errors()
    drain_answered(jobmaskinen._SITE)
    assert jobmaskinen.scrape({"role_targets": ["zzzqq"]}) == []
    assert "jobmaskinen" in drain_errors()
    assert drain_answered(jobmaskinen._SITE) is False


@responses.activate
def test_scrape_a_page_of_cards_does_not_signal_answered():
    _search("sygeplejerske", 1, "search_last_page.html")
    _detail("6530742")
    _detail("6529404")
    drain_answered(jobmaskinen._SITE)
    jobmaskinen.scrape({"role_targets": ["sygeplejerske"]})
    assert drain_answered(jobmaskinen._SITE) is False


@responses.activate
def test_scrape_reads_search_keywords_before_role_targets():
    _search("sygeplejerske", 1, "search_last_page.html")
    _detail("6530742")
    _detail("6529404")
    postings = jobmaskinen.scrape({"role_targets": ["x"], "search_keywords": ["sygeplejerske"]})
    assert len(postings) == 2


# --- probe -------------------------------------------------------------------------

def _probe_url() -> str:
    return jobmaskinen._search_url("elektriker", 1)


@responses.activate
def test_probe_ok_maps_the_cards_with_one_request():
    _serve(_probe_url(), _fx("search_page1.html"))
    drain_errors()

    result = jobmaskinen.probe(_CFG)

    assert result["structure_ok"] is True
    assert [p["platform_id"] for p in result["postings"]] == ["6535427", "6535434", "6535450"]
    assert [c.request.url for c in responses.calls] == [_probe_url()]
    assert drain_errors() == {}


@responses.activate
def test_probe_zero_hit_page_is_ok():
    _serve(_probe_url(), _fx("search_no_results.html"))
    drain_errors()
    result = jobmaskinen.probe(_CFG)
    assert result["structure_ok"] is True
    assert result["postings"] == []
    assert drain_errors() == {}


@responses.activate
def test_probe_drift_when_the_results_block_is_gone():
    _serve(_probe_url(), _fx("search_page1.html").replace("dbj_jobbox", "dbj_x").replace("dbj_jobHeadline", "dbj_y"))
    result = jobmaskinen.probe(_CFG)
    assert result["structure_ok"] is False
    assert result["reason"]


@responses.activate
def test_probe_forbidden_is_a_wall():
    _serve(_probe_url(), "Just a moment...", status=403)
    assert jobmaskinen.probe(_CFG)["wall"] is True


@responses.activate
def test_probe_connection_error_is_unreachable():
    _serve(_probe_url(), body=requests.exceptions.ConnectionError("down"))
    assert jobmaskinen.probe(_CFG)["unreachable"] is True


def test_probe_without_keywords_is_none():
    assert jobmaskinen.probe({"location": "Copenhagen"}) is None
