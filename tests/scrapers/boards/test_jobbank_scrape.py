"""Fixture tests for the full Akademikernes Jobbank scrape() path (jobbank.dk, plain HTML).

HTTP is mocked with `responses` from pages saved from the live site (search pages for the keyword
"reward", ad pages with their schema.org JobPosting JSON-LD; the ad text rewritten): two full pages
of 20 cards, a short last page, an empty page. No network.
"""

from pathlib import Path

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_pushback
from door.scrapers.boards import jobbank

_FIX = Path(__file__).parent / "fixtures" / "jobbank"
_CFG = {
    "search_keywords": ["reward"],
    "topic_terms": ["reward*", "compensation*", "compliance*"],
    "location": "Copenhagen",
}
# The on-topic ads of the saved pages, by page.
_PAGE1 = ["3133352", "3133445", "3133449", "3125524", "3119510", "3104812", "3147764"]
_PAGE2 = ["3095045", "3123940"]
_PAGE3 = ["3146289", "3137378"]  # 3095045 is on it again: a duplicate


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _serve(url: str, body: str | None = None, **kw) -> None:
    responses.add(responses.GET, url, body=body, **kw)


def _serve_search(keyword: str = "reward", *, pages: tuple[str, ...] = ("search_page1.html", "search_page2.html", "search_page3_short.html")) -> None:
    for n, name in enumerate(pages, 1):
        _serve(jobbank._search_url(keyword, n), _html(name))


def _serve_details(ids) -> None:
    for platform_id in ids:
        _serve(jobbank._detail_url(platform_id), _html(f"detail_{platform_id}.html"))


def _requested() -> list[str]:
    return [c.request.url for c in responses.calls]


@responses.activate
def test_scrape_paginates_dedups_gates_on_topic_and_reads_the_ads():
    _serve_search()
    _serve_details(_PAGE1 + _PAGE2 + _PAGE3)

    drain_errors()
    postings = jobbank.scrape(_CFG)

    assert [p["platform_id"] for p in postings] == _PAGE1 + _PAGE2 + _PAGE3
    assert drain_errors() == {}
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "jobbank"
        assert p["id"] == f"jobbank.{p['platform_id']}"
        assert p["title"] and p["company"] and p["url"] and p["description"]
        assert p["url"] == f"https://jobbank.dk/job/{p['platform_id']}/"
        assert "<" not in p["description"]
    # Off-topic cards ("Head of HR", the Benifex engineers, ...) cost no request: three search pages and the ads.
    assert len(_requested()) == 3 + len(postings)


@responses.activate
def test_an_english_and_a_danish_ad_both_come_through():
    _serve_search()
    _serve_details(_PAGE1 + _PAGE2 + _PAGE3)
    by_id = {p["platform_id"]: p for p in jobbank.scrape(_CFG)}

    accenture = by_id["3119510"]
    assert accenture["title"] == "Total Rewards Senior Analyst"
    assert accenture["company"] == "Accenture"
    assert accenture["location"] == "København S"
    assert accenture["posted_at"].startswith("2026-09-15")
    assert accenture["description"].startswith("About the role")

    forsvaret = by_id["3146289"]
    assert forsvaret["company"] == "Forsvaret"
    assert forsvaret["location"] == "Hjørring"
    assert forsvaret["posted_at"].startswith("2026-10-26")
    assert "søger en kollega" in forsvaret["description"]


@responses.activate
def test_an_ad_without_an_address_keeps_the_region_of_its_card():
    _serve_search()
    _serve_details(_PAGE1 + _PAGE2 + _PAGE3)
    voi = {p["platform_id"]: p for p in jobbank.scrape(_CFG)}["3147764"]
    assert voi["location"] == "Udlandet (Sverige)"
    assert voi["company"] == "VOI Denmark ApS"


@responses.activate
def test_known_ids_cost_no_ad_request():
    _serve_search()
    known = frozenset({"3133352", "3125524"})
    _serve_details([i for i in _PAGE1 + _PAGE2 + _PAGE3 if i not in known])

    out = jobbank.scrape(_CFG, known_ids=known)

    assert [p["platform_id"] for p in out if p.get("seen_only")] == ["3133352", "3125524"]
    assert not any("/job/3133352/" in u or "/job/3125524/" in u for u in _requested())
    assert len([p for p in out if not p.get("seen_only")]) == len(_PAGE1 + _PAGE2 + _PAGE3) - 2


@responses.activate
def test_a_short_page_ends_the_keyword_and_a_page_cap_bounds_it():
    _serve_search()
    _serve_details(_PAGE1)
    jobbank.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert [u for u in _requested() if "?key=" in u] == [jobbank._search_url("reward", 1)]

    responses.reset()
    _serve_search(pages=("search_page1.html", "search_page3_short.html"))
    _serve_details(_PAGE1 + _PAGE3 + ["3095045"])
    jobbank.scrape({**_CFG, "max_pages_per_keyword": 5})
    assert [u for u in _requested() if "?key=" in u] == [jobbank._search_url("reward", 1), jobbank._search_url("reward", 2)]


@responses.activate
def test_an_empty_page_ends_the_keyword_quietly():
    _serve(jobbank._search_url("reward", 1), _html("search_empty.html"))
    drain_errors()
    assert jobbank.scrape(_CFG) == []
    assert drain_errors() == {}
    assert _requested() == [jobbank._search_url("reward", 1)]


@responses.activate
def test_two_keywords_dedup_across_them():
    _serve_search("reward", pages=("search_page1.html",))
    _serve_search("compliance", pages=("search_page3_short.html",))
    _serve_details(_PAGE1 + _PAGE3 + ["3095045"])
    out = jobbank.scrape({**_CFG, "search_keywords": ["reward", "compliance"], "max_pages_per_keyword": 1})
    ids = [p["platform_id"] for p in out]
    assert len(ids) == len(set(ids)) == len(_PAGE1) + 3


@responses.activate
def test_role_targets_are_the_fallback_keywords():
    _serve(jobbank._search_url("reward", 1), _html("search_empty.html"))
    cfg = {"role_targets": ["reward"], "location": "Copenhagen"}
    assert jobbank.scrape(cfg) == []
    assert _requested() == [jobbank._search_url("reward", 1)]


@responses.activate
def test_a_failed_ad_request_is_recorded_and_the_rest_kept():
    _serve_search(pages=("search_page1.html",))
    _serve_details([i for i in _PAGE1 if i != "3125524"])
    _serve(jobbank._detail_url("3125524"), "boom", status=500)

    drain_errors()
    out = jobbank.scrape({**_CFG, "max_pages_per_keyword": 1})

    assert [p["platform_id"] for p in out] == [i for i in _PAGE1 if i != "3125524"]
    assert any("3125524" in e for e in drain_errors()["jobbank"])
    assert drain_pushback("jobbank") is False


@responses.activate
def test_an_ad_without_json_ld_is_recorded_not_raised():
    _serve_search(pages=("search_page1.html",))
    _serve_details([i for i in _PAGE1 if i != "3119510"])
    _serve(jobbank._detail_url("3119510"), "<html><body>no data</body></html>")
    drain_errors()
    out = jobbank.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert "3119510" not in [p["platform_id"] for p in out]
    assert any("3119510" in e for e in drain_errors()["jobbank"])


@responses.activate
def test_a_connection_error_is_recorded_not_raised():
    _serve(jobbank._search_url("reward", 1), body=requests.exceptions.ConnectionError("down"))
    drain_errors()
    assert jobbank.scrape(_CFG) == []
    [error] = drain_errors()["jobbank"]
    assert "reward" in error
    assert drain_pushback("jobbank") is False


@pytest.mark.parametrize("status", [403, 429])
@responses.activate
def test_a_refusal_on_a_search_page_is_pushback_and_stops_the_run(status):
    _serve(jobbank._search_url("reward", 1), "Access denied", status=status)
    drain_errors()
    drain_pushback("jobbank")

    assert jobbank.scrape({**_CFG, "search_keywords": ["reward", "compliance"]}) == []

    assert drain_pushback("jobbank") is True
    assert "jobbank" in drain_errors()
    assert not any("compliance" in u for u in _requested())  # the run stopped: no second keyword


@responses.activate
def test_a_challenge_page_with_status_200_is_pushback_too():
    _serve(jobbank._search_url("reward", 1), "<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/h/b'></script></html>")
    drain_errors()
    drain_pushback("jobbank")
    assert jobbank.scrape(_CFG) == []
    assert drain_pushback("jobbank") is True
    assert any("challenge" in e.lower() for e in drain_errors()["jobbank"])


@responses.activate
def test_a_refusal_on_an_ad_keeps_what_was_read_and_stops():
    _serve_search(pages=("search_page1.html",))
    _serve(jobbank._detail_url("3133352"), _html("detail_3133352.html"))
    _serve(jobbank._detail_url("3133445"), "slow down", status=429)
    drain_errors()
    drain_pushback("jobbank")

    out = jobbank.scrape({**_CFG, "max_pages_per_keyword": 1})

    assert [p["platform_id"] for p in out] == ["3133352"]
    assert drain_pushback("jobbank") is True
    assert not any("/job/3133449/" in u for u in _requested())


@pytest.mark.usefixtures("obey_robots")
@pytest.mark.real_robots
@responses.activate
def test_a_page_robots_disallows_is_never_loaded():
    responses.add(responses.GET, "https://jobbank.dk/robots.txt", body="User-agent: *\nDisallow: /job/\n")
    drain_errors()
    assert jobbank.scrape(_CFG) == []
    assert _requested() == ["https://jobbank.dk/robots.txt"]
    assert any("robots.txt disallows" in e for e in drain_errors()["jobbank"])


# --- probe ---------------------------------------------------------------------------------------

def _probe_url() -> str:
    return jobbank._search_url("reward", 1)


@responses.activate
def test_probe_ok_maps_the_cards_without_ad_requests():
    _serve(_probe_url(), _html("search_page1.html"))
    drain_errors()
    result = jobbank.probe(_CFG)
    assert result["structure_ok"] is True and result["ext"] == "html"
    assert len(result["postings"]) == 20
    for p in result["postings"]:
        JobPosting.model_validate(p)
    assert _requested() == [_probe_url()]
    assert "job-item" in result["raw"]
    assert drain_errors() == {}


@responses.activate
def test_probe_empty_result_page_is_ok():
    _serve(_probe_url(), _html("search_empty.html"))
    result = jobbank.probe(_CFG)
    assert result["structure_ok"] is True and result["postings"] == []


@responses.activate
def test_probe_drift_when_the_results_block_is_gone():
    _serve(_probe_url(), "<html><head><title>Akademikernes Jobbank</title></head><body><p>Vi er tilbage snart.</p></body></html>")
    result = jobbank.probe(_CFG)
    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")


@pytest.mark.parametrize("status", [401, 403, 429])
@responses.activate
def test_probe_refusal_is_a_wall(status):
    _serve(_probe_url(), "Just a moment...", status=status)
    assert jobbank.probe(_CFG)["wall"] is True


@responses.activate
def test_probe_challenge_page_is_a_wall():
    _serve(_probe_url(), "<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/h/b'></script></html>")
    result = jobbank.probe(_CFG)
    assert result["wall"] is True and result["structure_ok"] is False


@responses.activate
def test_probe_connection_error_is_unreachable():
    _serve(_probe_url(), body=requests.exceptions.ConnectionError("down"))
    assert jobbank.probe(_CFG)["unreachable"] is True


def test_probe_without_keywords_is_none():
    assert jobbank.probe({"location": "Copenhagen"}) is None
