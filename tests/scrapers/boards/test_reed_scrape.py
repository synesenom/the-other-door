"""Fixture tests for the full Reed scrape() path (reed.co.uk, Next.js page data).

HTTP is mocked with `responses` from pages saved from the live site (search "project manager" in London,
pages 1 and 2, trimmed to three ads each with their text rewritten and the result count set to 30 so
that page 2 is the last; one ad page with its schema.org JobPosting JSON-LD). No network.
"""

from datetime import datetime
from pathlib import Path

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_answered, drain_errors, drain_pushback
from door.scrapers.boards import reed

_FIX = Path(__file__).parent / "fixtures" / "reed"
_CFG = {"search_keywords": ["project manager"], "topic_terms": ["project*", "pmo*"], "location": "London"}
_PAGE1 = ["57458959", "57131623", "57505209"]
_PAGE2 = ["57487107", "57432153", "57404272"]
_URLS = {
    "57458959": "/jobs/project-manager/57458959", "57131623": "/jobs/senior-project-manager/57131623",
    "57505209": "/jobs/pmo-manager/57505209", "57487107": "/jobs/project-manager/57487107",
    "57432153": "/jobs/project-manager/57432153", "57404272": "/jobs/project-manager/57404272",
}


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _serve(url: str, body: str | None = None, **kw) -> None:
    responses.add(responses.GET, url, body=body, **kw)


def _search(keyword: str = "project manager", page: int = 1) -> str:
    return reed._search_url(keyword, "London", page)


def _serve_search(pages=("p1.html", "p2.html"), keyword: str = "project manager") -> None:
    for n, name in enumerate(pages, 1):
        _serve(_search(keyword, n), _html(name))


def _serve_details(ids) -> None:
    for i in ids:
        _serve("https://www.reed.co.uk" + _URLS[i], _html("detail.html"))


def _requested() -> list[str]:
    return [c.request.url for c in responses.calls]


@responses.activate
def test_scrape_paginates_and_reads_the_ads():
    _serve_search()
    _serve_details(_PAGE1 + _PAGE2)
    drain_errors()
    postings = reed.scrape(_CFG)

    assert [p["platform_id"] for p in postings] == _PAGE1 + _PAGE2
    assert drain_errors() == {}
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "reed" and p["id"] == f"reed.{p['platform_id']}"
        assert p["title"] and p["company"] and p["url"] and p["location"]
        assert p["description"].startswith("Project Manager, Payments") and "<" not in p["description"]
        assert p["url"] == "https://www.reed.co.uk" + _URLS[p["platform_id"]]
    assert [u for u in _requested() if "-jobs-in-" in u] == [_search(page=1), _search(page=2)]
    assert len(_requested()) == 2 + 6  # two search pages, six ads; page 2 was the last (30 hits)


@responses.activate
def test_card_fields_win_over_the_ad_page():
    _serve_search(("p1.html",))
    _serve_details(_PAGE1)
    by_id = {p["platform_id"]: p for p in reed.scrape({**_CFG, "max_pages_per_keyword": 1})}
    db = by_id["57505209"]
    assert db["title"] == "PMO Manager" and db["company"] == "Deutsche Bank" and db["location"] == "London"
    assert db["posted_at"].startswith("2026-10-29")


@responses.activate
def test_known_ids_cost_no_ad_request():
    _serve_search()
    known = frozenset({"57458959", "57432153"})
    _serve_details([i for i in _PAGE1 + _PAGE2 if i not in known])
    out = reed.scrape(_CFG, known_ids=known)
    assert [p["platform_id"] for p in out if p.get("seen_only")] == ["57458959", "57432153"]
    assert not any("57458959" in u or "57432153" in u for u in _requested() if "pageno" not in u and "jobs-in" not in u)
    assert len([p for p in out if not p.get("seen_only")]) == 4


@responses.activate
def test_off_topic_titles_cost_no_ad_request():
    _serve_search(("p1.html",), keyword="pmo")
    _serve_details(["57505209"])
    out = reed.scrape({**_CFG, "search_keywords": ["pmo"], "topic_terms": ["pmo*"], "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == ["57505209"]
    assert len(_requested()) == 2


@responses.activate
def test_since_cuts_old_ads_before_their_request():
    _serve_search(("p1.html",))
    _serve_details(["57458959", "57505209"])
    out = reed.scrape({**_CFG, "max_pages_per_keyword": 1}, since=datetime(2026, 10, 1))
    assert [p["platform_id"] for p in out] == ["57458959", "57505209"]  # 57131623 is from July
    assert not any("57131623" in u for u in _requested())


@responses.activate
def test_a_page_cap_bounds_the_keyword():
    _serve_search(("p1.html",))
    _serve_details(_PAGE1)
    reed.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert [u for u in _requested() if "-jobs-in-" in u] == [_search(page=1)]


@responses.activate
def test_the_last_page_by_result_count_ends_the_keyword():
    body = _html("p1.html").replace('"count": 30', '"count": 3')
    _serve(_search(page=1), body)
    _serve_details(_PAGE1)
    reed.scrape({**_CFG, "max_pages_per_keyword": 5})
    assert [u for u in _requested() if "-jobs-in-" in u] == [_search(page=1)]


@responses.activate
def test_an_empty_page_ends_the_keyword_quietly():
    empty = '<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"searchResults":{"count":0,"jobs":[]}}}}</script>'
    _serve(_search(page=1), empty)
    drain_errors()
    drain_answered("reed")
    assert reed.scrape(_CFG) == []
    assert drain_errors() == {}
    assert drain_answered("reed") is True
    assert _requested() == [_search(page=1)]


@responses.activate
def test_a_real_zero_hit_page_is_an_answer():
    _serve(_search(page=1), _html("search_empty.html"))
    drain_errors()
    drain_answered("reed")
    assert reed.scrape(_CFG) == []
    assert drain_errors() == {}
    assert drain_answered("reed") is True


@responses.activate
def test_a_page_without_results_block_is_recorded_not_answered():
    _serve(_search(page=1), "<html><body>Something else</body></html>")
    drain_errors()
    drain_answered("reed")
    assert reed.scrape(_CFG) == []
    assert "reed" in drain_errors()
    assert drain_answered("reed") is False


@responses.activate
def test_two_keywords_dedup_across_them():
    _serve(_search("project manager"), _html("p1.html"))
    _serve(_search("project lead"), _html("p1.html"))
    _serve_details(_PAGE1)
    out = reed.scrape({**_CFG, "search_keywords": ["project manager", "project lead"], "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == _PAGE1


@responses.activate
def test_role_targets_are_the_fallback_keywords():
    _serve(_search(), '<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"searchResults":{"count":0,"jobs":[]}}}}</script>')
    assert reed.scrape({"role_targets": ["project manager"], "location": "London"}) == []
    assert _requested() == [_search()]


@responses.activate
def test_a_failed_ad_request_is_recorded_and_the_snippet_kept():
    _serve_search(("p1.html",))
    _serve_details(["57458959", "57131623"])
    _serve("https://www.reed.co.uk" + _URLS["57505209"], "boom", status=500)
    drain_errors()
    out = reed.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == _PAGE1
    assert out[2]["description"].startswith("PMO Manager to support")
    assert any("57505209" in e for e in drain_errors()["reed"])
    assert drain_pushback("reed") is False


@responses.activate
def test_an_ad_without_json_ld_is_recorded_and_the_snippet_kept():
    _serve_search(("p1.html",))
    _serve_details(["57458959", "57131623"])
    _serve("https://www.reed.co.uk" + _URLS["57505209"], "<html><body>no data</body></html>")
    drain_errors()
    out = reed.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert out[2]["description"].startswith("PMO Manager to support")
    assert any("57505209" in e for e in drain_errors()["reed"])


@responses.activate
def test_a_connection_error_is_recorded_not_raised():
    _serve(_search(), body=requests.exceptions.ConnectionError("down"))
    drain_errors()
    assert reed.scrape(_CFG) == []
    [error] = drain_errors()["reed"]
    assert "project manager" in error
    assert drain_pushback("reed") is False


@pytest.mark.parametrize("status", [403, 429])
@responses.activate
def test_a_refusal_on_a_search_page_is_pushback_and_stops_the_run(status):
    _serve(_search(), "Access denied", status=status)
    drain_errors()
    drain_pushback("reed")
    assert reed.scrape({**_CFG, "search_keywords": ["project manager", "pmo"]}) == []
    assert drain_pushback("reed") is True
    assert "reed" in drain_errors()
    assert not any("pmo" in u for u in _requested())


@responses.activate
def test_a_challenge_page_with_status_200_is_pushback_too():
    _serve(_search(), "<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/h/b'></script></html>")
    drain_errors()
    drain_pushback("reed")
    assert reed.scrape(_CFG) == []
    assert drain_pushback("reed") is True


@responses.activate
def test_a_refusal_on_an_ad_keeps_what_was_read_and_stops():
    _serve_search(("p1.html",))
    _serve_details(["57458959"])
    _serve("https://www.reed.co.uk" + _URLS["57131623"], "slow down", status=429)
    drain_errors()
    drain_pushback("reed")
    out = reed.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == ["57458959"]
    assert drain_pushback("reed") is True
    assert not any("57505209" in u for u in _requested())


# --- probe ---------------------------------------------------------------------------------------

@responses.activate
def test_probe_ok_maps_the_cards_without_ad_requests():
    _serve(_search(), _html("p1.html"))
    drain_errors()
    result = reed.probe(_CFG)
    assert result["structure_ok"] is True and result["ext"] == "html"
    assert len(result["postings"]) == 3
    for p in result["postings"]:
        JobPosting.model_validate(p)
    assert _requested() == [_search()]
    assert drain_errors() == {}


@responses.activate
def test_probe_drift_when_the_results_block_is_removed():
    _serve(_search(), _html("p1.html").replace("searchResults", "gone"))
    result = reed.probe(_CFG)
    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")


@pytest.mark.parametrize("status", [401, 403, 429])
@responses.activate
def test_probe_refusal_is_a_wall(status):
    _serve(_search(), "Just a moment...", status=status)
    assert reed.probe(_CFG)["wall"] is True


@responses.activate
def test_probe_challenge_page_is_a_wall():
    _serve(_search(), "<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/h/b'></script></html>")
    result = reed.probe(_CFG)
    assert result["wall"] is True and result["structure_ok"] is False


@responses.activate
def test_probe_connection_error_is_unreachable():
    _serve(_search(), body=requests.exceptions.ConnectionError("down"))
    assert reed.probe(_CFG)["unreachable"] is True


def test_probe_without_keywords_is_none():
    assert reed.probe({"location": "London"}) is None
