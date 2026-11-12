"""Fixture tests for the full Choisir le service public scrape() path (choisirleservicepublic.gouv.fr, plain HTTP).

HTTP is mocked with `responses` from pages saved from the live site (searches for "data scientist" in
Île-de-France, the ad pages; the ad text rewritten): two result pages, a page with only off-topic ads
and a next link, an English-titled page, an empty answer. No network.
"""

from datetime import datetime
from pathlib import Path

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_pushback
from door.scrapers.boards import choisirleservicepublic as csp

_FIX = Path(__file__).parent / "fixtures" / "choisirleservicepublic"
_CFG = {"search_keywords": ["data scientist"], "topic_terms": ["data scientist*", "data science*"], "location": "Paris"}
_AD = "https://choisirleservicepublic.gouv.fr/offre-emploi/"
_URLS = {
    "2026-2452785": _AD + "data-scientist-confirmee-reference-2026-2452785/",
    "MEF_2026-33266": _AD + "dgddi---dnred-ingenieur-data-scientiste-hf-reference-MEF_2026-33266/",
    "MINT_BS075PNA-121850": _AD + "chef-de-projet-data-science---valorisation-et-diffusion-des-donnees-sur-la-delinquance-reference-MINT_BS075PNA-121850/",
    "2026-2423164": _AD + "grant-desk-coordinator-engageeu-reference-2026-2423164/",
    "2026-2252366": _AD + "india-expert-technique-international-eti-at-indo-french-center-for-the-promotion-of-advanced-research-reference-2026-2252366/",
}
_PAGE1 = ["2026-2452785", "MEF_2026-33266"]  # the third card, an OSINT analyst, is off topic
_PAGE2 = ["MINT_BS075PNA-121850"]  # and so is its second
_ALL = _PAGE1 + _PAGE2


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _serve(url: str, body: str | None = None, **kw) -> None:
    responses.add(responses.GET, url, body=body, **kw)


def _url(keyword: str, page: int, *, loc: str | None = "208") -> str:
    return csp._search_url(keyword, loc, page)


def _serve_search(keyword: str = "data scientist", pages: tuple[str, ...] = ("search_page1.html", "search_page2.html")) -> None:
    for n, name in enumerate(pages, 1):
        _serve(_url(keyword, n), _html(name))


def _serve_details(ids) -> None:
    for platform_id in ids:
        _serve(_URLS[platform_id], _html(f"detail/{platform_id}.html"))


def _requested() -> list[str]:
    return [c.request.url for c in responses.calls]


def _searches() -> list[str]:
    return [u for u in _requested() if "/nos-offres/" in u]


@responses.activate
def test_scrape_paginates_gates_on_topic_and_reads_the_ads():
    _serve_search()
    _serve_details(_ALL)

    drain_errors()
    postings = csp.scrape(_CFG)

    assert [p["platform_id"] for p in postings] == _ALL
    assert drain_errors() == {}
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "choisirleservicepublic"
        assert p["id"] == f"choisirleservicepublic.{p['platform_id'].lower()}"
        assert p["title"] and p["company"] and p["url"] and p["description"]
        assert p["url"] == _URLS[p["platform_id"]]
        assert "<" not in p["description"]
    # The off-topic OSINT cards cost no request: two search pages and one ad page per on-topic ad.
    assert len(_requested()) == 2 + len(postings)
    assert _searches() == [_url("data scientist", 1), _url("data scientist", 2)]


@responses.activate
def test_mapping_of_an_ad_with_its_employer_place_and_date():
    _serve_search()
    _serve_details(_ALL)
    by_id = {p["platform_id"]: p for p in csp.scrape(_CFG)}

    ad = by_id["2026-2452785"]
    assert ad["title"] == "Data Scientist confirmé(e)"
    assert ad["company"] == "DSJ-SD - CCAS-Greffe"
    assert ad["location"] == "Paris (75)"
    assert ad["posted_at"].startswith("2026-10-27")
    assert ad["description"].startswith("Vos missions en quelques mots")
    assert "Python, SQL" in ad["description"]
    dnred = by_id["MEF_2026-33266"]
    assert dnred["company"] == "Direction nationale du renseignement et des enquêtes douanières (DNRED)"
    assert dnred["location"] == "Val de Marne (94)"
    assert dnred["posted_at"].startswith("2026-10-22")


@responses.activate
def test_english_ads_come_through_with_the_french_ones():
    _serve_search("grant desk", pages=("search_english.html",))
    _serve_details(["2026-2423164", "2026-2252366"])
    out = csp.scrape({**_CFG, "search_keywords": ["grant desk"], "topic_terms": ["grant*", "expert*"]})
    by_id = {p["platform_id"]: p for p in out}
    assert [p["title"] for p in out] == [
        "GRANT DESK COORDINATOR (Engage.Eu)",
        "INDIA-Expert Technique International (ETI) at Indo-French Center for the Promotion of Advanced Research",
    ]
    assert "Grant Desk Coordinator will follow" in by_id["2026-2423164"]["description"]
    assert by_id["2026-2423164"]["company"] == "Université Toulouse Capitole"
    assert "Main tasks and expected outcomes" in by_id["2026-2252366"]["description"]


@responses.activate
def test_known_ids_cost_no_ad_request():
    _serve_search()
    known = frozenset({"2026-2452785", "MINT_BS075PNA-121850"})
    _serve_details([i for i in _ALL if i not in known])

    out = csp.scrape(_CFG, known_ids=known)

    assert [p["platform_id"] for p in out if p.get("seen_only")] == ["2026-2452785", "MINT_BS075PNA-121850"]
    assert _URLS["2026-2452785"] not in _requested() and _URLS["MINT_BS075PNA-121850"] not in _requested()
    assert len([p for p in out if not p.get("seen_only")]) == 1


@responses.activate
def test_a_page_without_a_next_link_ends_the_keyword_and_a_page_cap_bounds_it():
    _serve_search(pages=("search_page1.html", "search_page2.html"))
    _serve_details(_ALL)
    csp.scrape(_CFG)
    assert _searches() == [_url("data scientist", 1), _url("data scientist", 2)]  # page 2 has no next link: no page 3

    responses.reset()
    _serve_search()
    _serve_details(_PAGE1)
    csp.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert _searches() == [_url("data scientist", 1)]


@responses.activate
def test_a_page_with_no_on_topic_ad_ends_the_keyword():
    # The site's text search is fuzzy: after the on-topic ads it lists unrelated ones, page after page.
    _serve(_url("data scientist", 1), _html("search_offtopic.html"))
    drain_errors()
    assert csp.scrape(_CFG) == []
    assert drain_errors() == {}
    assert _requested() == [_url("data scientist", 1)]


@responses.activate
def test_an_empty_answer_ends_the_keyword_quietly():
    _serve(_url("zzzxqv", 1), _html("search_empty.html"))
    drain_errors()
    assert csp.scrape({**_CFG, "search_keywords": ["zzzxqv"]}) == []
    assert drain_errors() == {}
    assert _requested() == [_url("zzzxqv", 1)]


@responses.activate
def test_two_keywords_dedup_across_them():
    _serve_search("data scientist", pages=("search_page1.html",))
    _serve_search("data science", pages=("search_page1.html",))
    _serve_details(_PAGE1)
    out = csp.scrape({**_CFG, "search_keywords": ["data scientist", "data science"], "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == _PAGE1


@responses.activate
def test_role_targets_are_the_fallback_keywords():
    _serve(_url("data scientist", 1), _html("search_empty.html"))
    assert csp.scrape({"role_targets": ["data scientist"], "location": "Paris"}) == []
    assert _requested() == [_url("data scientist", 1)]


@responses.activate
def test_location_shapes_the_search_and_since_is_left_to_the_engine():
    _serve(_url("comptable", 1, loc="336"), _html("search_empty.html"))
    csp.scrape({"search_keywords": ["comptable"], "location": "Lyon"}, since=datetime(2026, 10, 25))
    assert _requested() == [_url("comptable", 1, loc="336")]

    responses.reset()
    _serve(_url("comptable", 1, loc=None), _html("search_empty.html"))
    csp.scrape({"search_keywords": ["comptable"], "location": "Quimper"})
    assert _requested() == [_url("comptable", 1, loc=None)]
    assert "localisation" not in _requested()[0]


@responses.activate
def test_a_failed_ad_request_is_recorded_and_the_rest_kept():
    _serve_search(pages=("search_page1.html",))
    _serve_details(["MEF_2026-33266"])
    _serve(_URLS["2026-2452785"], "boom", status=500)

    drain_errors()
    out = csp.scrape({**_CFG, "max_pages_per_keyword": 1})

    assert [p["platform_id"] for p in out] == ["MEF_2026-33266"]
    assert any("2026-2452785" in e for e in drain_errors()["choisirleservicepublic"])
    assert drain_pushback("choisirleservicepublic") is False


@responses.activate
def test_an_ad_page_without_text_is_recorded_not_raised():
    _serve_search(pages=("search_page1.html",))
    _serve_details(["MEF_2026-33266"])
    _serve(_URLS["2026-2452785"], "<html><body><p>Cette offre n'est plus disponible</p></body></html>")
    drain_errors()
    out = csp.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == ["MEF_2026-33266"]
    assert any("2026-2452785" in e for e in drain_errors()["choisirleservicepublic"])


@responses.activate
def test_a_connection_error_is_recorded_not_raised():
    _serve(_url("data scientist", 1), body=requests.exceptions.ConnectionError("down"))
    drain_errors()
    assert csp.scrape(_CFG) == []
    [error] = drain_errors()["choisirleservicepublic"]
    assert "data scientist" in error
    assert drain_pushback("choisirleservicepublic") is False


@responses.activate
def test_a_page_that_is_not_a_result_list_is_recorded_as_a_change():
    _serve(_url("data scientist", 1), "<html><body><p>Page introuvable</p></body></html>")
    drain_errors()
    assert csp.scrape(_CFG) == []
    assert any("result list" in e for e in drain_errors()["choisirleservicepublic"])


@pytest.mark.parametrize("status", [403, 429])
@responses.activate
def test_a_refusal_on_a_search_page_is_pushback_and_stops_the_run(status):
    _serve(_url("data scientist", 1), "Access denied", status=status)
    drain_errors()
    drain_pushback("choisirleservicepublic")

    assert csp.scrape({**_CFG, "search_keywords": ["data scientist", "comptable"]}) == []

    assert drain_pushback("choisirleservicepublic") is True
    assert "choisirleservicepublic" in drain_errors()
    assert not any("comptable" in u for u in _requested())  # the run stopped: no second keyword


@responses.activate
def test_a_refusal_on_an_ad_keeps_what_was_read_and_stops():
    _serve_search(pages=("search_page1.html",))
    _serve_details(["2026-2452785"])
    _serve(_URLS["MEF_2026-33266"], "slow down", status=429)
    drain_errors()
    drain_pushback("choisirleservicepublic")

    out = csp.scrape({**_CFG, "max_pages_per_keyword": 1})

    assert [p["platform_id"] for p in out] == ["2026-2452785"]
    assert drain_pushback("choisirleservicepublic") is True


@pytest.mark.usefixtures("obey_robots")
@pytest.mark.real_robots
@responses.activate
def test_a_page_robots_disallows_is_never_loaded():
    responses.add(responses.GET, "https://choisirleservicepublic.gouv.fr/robots.txt", body="User-agent: *\nDisallow: /nos-offres/\n")
    drain_errors()
    assert csp.scrape(_CFG) == []
    assert _requested() == ["https://choisirleservicepublic.gouv.fr/robots.txt"]
    assert any("robots.txt disallows" in e for e in drain_errors()["choisirleservicepublic"])


# --- probe ---------------------------------------------------------------------------------------

def _probe_url() -> str:
    return _url("data scientist", 1)


@responses.activate
def test_probe_ok_maps_the_cards_without_ad_requests():
    _serve(_probe_url(), _html("search_page1.html"))
    drain_errors()
    result = csp.probe(_CFG)
    assert result["structure_ok"] is True and result["ext"] == "html"
    assert len(result["postings"]) == 3
    for p in result["postings"]:
        JobPosting.model_validate(p)
    assert _requested() == [_probe_url()]
    assert "fr-card--offer" in result["raw"]
    assert drain_errors() == {}


@responses.activate
def test_probe_empty_answer_is_ok():
    _serve(_probe_url(), _html("search_empty.html"))
    result = csp.probe(_CFG)
    assert result["structure_ok"] is True and result["postings"] == []


@responses.activate
def test_probe_drift_when_the_results_block_is_gone():
    _serve(_probe_url(), _html("search_page1.html").replace("fr-card--offer", "fr-card--other").replace("js-results", "js-other"))
    result = csp.probe(_CFG)
    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")


@responses.activate
def test_probe_drift_when_the_cards_lose_their_links():
    _serve(_probe_url(), _html("search_page1.html").replace("-reference-", "-ref-"))
    result = csp.probe(_CFG)
    assert result["structure_ok"] is False and result["reason"]


@pytest.mark.parametrize("status", [401, 403, 429])
@responses.activate
def test_probe_refusal_is_a_wall(status):
    _serve(_probe_url(), "Access denied", status=status)
    assert csp.probe(_CFG)["wall"] is True


@responses.activate
def test_probe_connection_error_is_unreachable():
    _serve(_probe_url(), body=requests.exceptions.ConnectionError("down"))
    assert csp.probe(_CFG)["unreachable"] is True


def test_probe_without_keywords_is_none():
    assert csp.probe({"location": "Paris"}) is None
