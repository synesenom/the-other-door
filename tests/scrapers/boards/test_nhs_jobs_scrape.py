"""Fixture tests for the full NHS Jobs scrape() path (server-rendered search pages and ad pages).

HTTP is mocked with `responses` from pages saved from the live site (search "project manager", London,
newest first, pages 1 and 2 trimmed to three ads each; one ad page, text rewritten). No network.
"""

from datetime import datetime
from pathlib import Path

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_answered, drain_errors, drain_pushback
from door.scrapers.boards import nhs_jobs

_FIX = Path(__file__).parent / "fixtures" / "nhs_jobs"
_CFG = {"search_keywords": ["project manager"], "topic_terms": ["change*", "analyst*", "procurement*", "commercial*"], "location": "London"}
_PAGE1 = ["C9200-26-1002", "C9200-26-1001"]  # C9363-26-1283 (EMHP / CBT Practitioner) is off topic
_PAGE2 = ["M0048-26-0532", "M9290-26-0067"]  # C9282-26-0944 (Staff Nurse) is off topic
_AD = "https://www.jobs.nhs.uk/candidate/jobadvert/"


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _serve(url: str, body: str | None = None, **kw) -> None:
    responses.add(responses.GET, url, body=body, **kw)


def _search(keyword: str = "project manager", page: int = 1, location: str = "London") -> str:
    return nhs_jobs._search_url(keyword, location, page)


def _serve_search(pages=("p1.html", "p2.html"), keyword: str = "project manager") -> None:
    for n, name in enumerate(pages, 1):
        _serve(_search(keyword, n), _html(name))


def _serve_details(ids) -> None:
    for i in ids:
        _serve(_AD + i, _html("detail.html"))


def _requested() -> list[str]:
    return [c.request.url for c in responses.calls]


def _searches() -> list[str]:
    return [u for u in _requested() if "/search/results" in u]


@responses.activate
def test_scrape_paginates_and_reads_the_ads():
    _serve_search()
    _serve_details(_PAGE1 + _PAGE2)
    drain_errors()
    postings = nhs_jobs.scrape({**_CFG, "max_pages_per_keyword": 2})

    assert [p["platform_id"] for p in postings] == _PAGE1 + _PAGE2
    assert drain_errors() == {}
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "nhs_jobs" and p["id"] == f"nhs_jobs.{p['platform_id'].lower()}"
        assert p["title"] and p["company"] and p["url"] and "London" in p["location"]
        assert "change manager to join" in p["description"] and "<" not in p["description"]
        assert p["url"] == _AD + p["platform_id"]
    assert _searches() == [_search(page=1), _search(page=2)]
    assert len(_requested()) == 2 + 4  # two search pages, four on-topic ads


@responses.activate
def test_card_fields_and_the_ad_date_map_to_the_posting():
    _serve_search(("p1.html",))
    _serve_details(_PAGE1)
    by_id = {p["platform_id"]: p for p in nhs_jobs.scrape({**_CFG, "max_pages_per_keyword": 1})}
    p = by_id["C9200-26-1001"]
    assert p["title"] == "IDT Change Manager" and p["company"] == "St George's University Hospitals NHS Foundation Trust"
    assert p["posted_at"].startswith("2026-11-03")


@responses.activate
def test_known_ids_cost_no_ad_request():
    _serve_search(("p1.html",))
    _serve_details(["C9200-26-1001"])
    out = nhs_jobs.scrape({**_CFG, "max_pages_per_keyword": 1}, known_ids=frozenset({"C9200-26-1002"}))
    assert out[0] == {"platform_id": "C9200-26-1002", "seen_only": True}
    assert not any("1002" in u for u in _requested() if "/jobadvert/" in u)
    assert len(out) == 2


@responses.activate
def test_off_topic_titles_cost_no_ad_request():
    _serve_search()
    _serve_details(_PAGE1 + _PAGE2)
    nhs_jobs.scrape({**_CFG, "max_pages_per_keyword": 2})
    assert not any("C9363-26-1283" in u or "C9282-26-0944" in u for u in _requested())


@responses.activate
def test_cards_in_another_place_cost_no_ad_request():
    body = _html("p1.html").replace("London SW17 0QT", "Glasgow G1 1AA", 1)
    _serve(_search(), body)
    _serve_details(["C9200-26-1001"])
    out = nhs_jobs.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == ["C9200-26-1001"]
    assert not any("1002" in u for u in _requested())


@responses.activate
def test_the_ads_own_place_replaces_the_trusts_and_an_out_of_area_ad_is_dropped():
    _serve_search(("p1.html",))
    here = _html("detail.html")
    away = here.replace('id="employer_town">London', 'id="employer_town">Birmingham').replace(
        'id="employer_county"></p>', 'id="employer_county">West Midlands</p>')
    _serve(_AD + "C9200-26-1002", away)
    _serve(_AD + "C9200-26-1001", here)
    out = nhs_jobs.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == ["C9200-26-1001"]
    assert out[0]["location"] == "London"


@responses.activate
def test_the_ads_own_place_is_the_postings_location():
    _serve_search(("p1.html",))
    page = _html("detail.html").replace('id="employer_town">London', 'id="employer_town">Croydon')
    _serve(_AD + "C9200-26-1002", _html("detail.html"))
    _serve(_AD + "C9200-26-1001", page)
    out = nhs_jobs.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert {p["platform_id"]: p["location"] for p in out}["C9200-26-1001"] == "Croydon"


@responses.activate
def test_since_ends_the_keyword_at_the_first_older_ad():
    _serve_search()
    out = nhs_jobs.scrape(_CFG, since=datetime(2026, 11, 4))
    assert out == []  # newest first: the first card (3 November) is older, so is everything after it
    assert _requested() == [_search(page=1)]


@responses.activate
def test_since_keeps_ads_posted_on_that_day():
    _serve_search(("p1.html",))
    _serve_details(_PAGE1)
    out = nhs_jobs.scrape({**_CFG, "max_pages_per_keyword": 1}, since=datetime(2026, 11, 3))
    assert [p["platform_id"] for p in out] == _PAGE1


@responses.activate
def test_a_page_cap_bounds_the_keyword():
    _serve_search(("p1.html",))
    _serve_details(_PAGE1)
    nhs_jobs.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert _searches() == [_search(page=1)]


@responses.activate
def test_an_empty_page_ends_the_keyword_quietly():
    _serve(_search(), '<html><h1 data-test="search-result-query">0 jobs found for project manager</h1><ul class="nhsuk-list search-results"></ul></html>')
    drain_errors()
    drain_answered("nhs_jobs")
    assert nhs_jobs.scrape(_CFG) == []
    assert drain_errors() == {}
    assert drain_answered("nhs_jobs") is True
    assert _requested() == [_search()]


@responses.activate
def test_a_page_without_results_block_is_recorded():
    _serve(_search(), "<html><body>Service Domain Information</body></html>")
    drain_errors()
    drain_answered("nhs_jobs")
    assert nhs_jobs.scrape(_CFG) == []
    assert "nhs_jobs" in drain_errors()
    assert drain_answered("nhs_jobs") is False


@responses.activate
def test_a_real_zero_hit_page_is_an_answer():
    _serve(_search(), _html("search_empty.html"))
    drain_errors()
    drain_answered("nhs_jobs")
    assert nhs_jobs.scrape(_CFG) == []
    assert drain_errors() == {}
    assert drain_answered("nhs_jobs") is True


@responses.activate
def test_two_keywords_dedup_across_them():
    _serve(_search("project manager"), _html("p1.html"))
    _serve(_search("change manager"), _html("p1.html"))
    _serve_details(_PAGE1)
    out = nhs_jobs.scrape({**_CFG, "search_keywords": ["project manager", "change manager"], "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == _PAGE1


@responses.activate
def test_a_failed_ad_request_is_recorded_and_the_card_kept():
    _serve_search(("p1.html",))
    _serve(_AD + "C9200-26-1002", "boom", status=500)
    _serve_details(["C9200-26-1001"])
    drain_errors()
    out = nhs_jobs.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == _PAGE1
    assert "IDT Senior Change Analyst" in out[0]["description"]
    assert any("C9200-26-1002" in e for e in drain_errors()["nhs_jobs"])
    assert drain_pushback("nhs_jobs") is False


@responses.activate
def test_an_ad_without_description_is_recorded_and_the_card_kept():
    _serve_search(("p1.html",))
    _serve(_AD + "C9200-26-1002", "<html><body>no data</body></html>")
    _serve_details(["C9200-26-1001"])
    drain_errors()
    out = nhs_jobs.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert len(out) == 2 and out[0]["description"]
    assert any("C9200-26-1002" in e for e in drain_errors()["nhs_jobs"])


@responses.activate
def test_a_connection_error_is_recorded_not_raised():
    _serve(_search(), body=requests.exceptions.ConnectionError("down"))
    drain_errors()
    assert nhs_jobs.scrape(_CFG) == []
    [error] = drain_errors()["nhs_jobs"]
    assert "project manager" in error
    assert drain_pushback("nhs_jobs") is False


@pytest.mark.parametrize("status", [403, 429])
@responses.activate
def test_a_refusal_on_a_search_page_is_pushback_and_stops_the_run(status):
    _serve(_search(), "Access denied", status=status)
    drain_errors()
    drain_pushback("nhs_jobs")
    assert nhs_jobs.scrape({**_CFG, "search_keywords": ["project manager", "change manager"]}) == []
    assert drain_pushback("nhs_jobs") is True
    assert "nhs_jobs" in drain_errors()
    assert not any("change+manager" in u for u in _requested())


@responses.activate
def test_a_refusal_on_an_ad_keeps_what_was_read_and_stops():
    _serve_search(("p1.html",))
    _serve(_AD + "C9200-26-1002", "slow down", status=429)
    drain_errors()
    drain_pushback("nhs_jobs")
    out = nhs_jobs.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert out == []
    assert drain_pushback("nhs_jobs") is True
    assert not any("1001" in u for u in _requested() if "/jobadvert/" in u)


# --- probe ---------------------------------------------------------------------------------------

@responses.activate
def test_probe_ok_maps_the_cards_without_ad_requests():
    _serve(_search(), _html("p1.html"))
    drain_errors()
    result = nhs_jobs.probe(_CFG)
    assert result["structure_ok"] is True and result["ext"] == "html"
    assert len(result["postings"]) == 3
    for p in result["postings"]:
        JobPosting.model_validate(p)
    assert _requested() == [_search()]
    assert drain_errors() == {}


@responses.activate
def test_probe_drift_when_the_results_block_is_removed():
    _serve(_search(), _html("p1.html").replace('data-test="search-result"', 'data-test="gone"').replace("search-result-query", "gone"))
    result = nhs_jobs.probe(_CFG)
    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")


@pytest.mark.parametrize("status", [401, 403, 429])
@responses.activate
def test_probe_refusal_is_a_wall(status):
    _serve(_search(), "Just a moment...", status=status)
    assert nhs_jobs.probe(_CFG)["wall"] is True


@responses.activate
def test_probe_connection_error_is_unreachable():
    _serve(_search(), body=requests.exceptions.ConnectionError("down"))
    assert nhs_jobs.probe(_CFG)["unreachable"] is True


def test_probe_without_keywords_is_none():
    assert nhs_jobs.probe({"location": "London"}) is None
