"""Fixture tests for the full France Travail scrape() path (candidat.francetravail.fr, plain HTTP).

HTTP is mocked with `responses` from pages saved from the live site (searches for "chef de projet" and
"software engineer" in Paris, the JSON each ad's description component loads; the ad text rewritten):
three pages, a short last page, an empty answer. No network.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_answered, drain_errors, drain_pushback
from door.scrapers.boards import francetravail

_FIX = Path(__file__).parent / "fixtures" / "francetravail"
_CFG = {
    "search_keywords": ["chef de projet"],
    "topic_terms": ["chef de projet*", "project manager*", "software engineer*"],
    "location": "Paris",
}
_PAGE1 = ["8441867", "8441811", "8433015", "8450510"]
_PAGE2 = ["8436381", "8433708"]  # the third card, a Product Owner, is off topic
_PAGE3 = ["215WLWF", "8440950"]
_ALL = _PAGE1 + _PAGE2 + _PAGE3


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _serve(url: str, body: str | None = None, **kw) -> None:
    responses.add(responses.GET, url, body=body, **kw)


def _url(keyword: str, page: int, *, code: str | None = "75056", emission: int = 31) -> str:
    return francetravail._search_url(keyword, code, emission, page)


def _serve_search(keyword: str = "chef de projet", pages: tuple[str, ...] = ("search_page1.html", "search_page2.html", "search_page3.html")) -> None:
    for n, name in enumerate(pages, 1):
        _serve(_url(keyword, n), _html(name))


def _serve_details(ids) -> None:
    for platform_id in ids:
        _serve(francetravail._detail_url(platform_id), (_FIX / "detail" / f"{platform_id}.json").read_text(encoding="utf-8"),
               content_type="application/json")


def _requested() -> list[str]:
    return [c.request.url for c in responses.calls]


def _searches() -> list[str]:
    return [u for u in _requested() if "/offres/recherche?" in u]


@responses.activate
def test_scrape_paginates_gates_on_topic_and_reads_the_ads():
    _serve_search()
    _serve_details(_ALL)

    drain_errors()
    postings = francetravail.scrape(_CFG)

    assert [p["platform_id"] for p in postings] == _ALL
    assert drain_errors() == {}
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "francetravail"
        assert p["id"] == f"francetravail.{p['platform_id'].lower()}"
        assert p["title"] and p["url"] and p["description"]
        assert p["url"] == f"https://candidat.francetravail.fr/offres/recherche/detail/{p['platform_id']}"
        assert "<" not in p["description"]
    # The off-topic Product Owner costs no request: three search pages and one description per ad.
    assert len(_requested()) == 3 + len(postings)
    assert [u for u in _searches()] == [_url("chef de projet", n) for n in (1, 2, 3)]


@responses.activate
def test_mapping_of_an_ad_with_its_employer_place_and_date():
    _serve_search()
    _serve_details(_ALL)
    by_id = {p["platform_id"]: p for p in francetravail.scrape(_CFG)}

    hn = by_id["8441867"]
    assert hn["title"] == "Chef de Projet Si - MOE - Paiements H/F"
    assert hn["company"] == "HN Services"
    assert hn["location"] == "75 - Paris 1er Arrondissement"
    assert hn["description"].startswith("POSTE : Chef de Projet Si - MOE - Paiements H/F")
    today = datetime.now().date()
    assert hn["posted_at"].startswith(today.isoformat())
    # "Publié hier", from a direct posting (an alphanumeric id).
    nrj = by_id["215WLWF"]
    assert nrj["company"] == "NRJ GROUP"
    assert nrj["posted_at"].startswith((today - timedelta(days=1)).isoformat())


@responses.activate
def test_an_anonymous_ad_has_an_empty_company():
    _serve_search(pages=("search_page1.html",))
    _serve_details(_PAGE1)
    ad = {p["platform_id"]: p for p in francetravail.scrape({**_CFG, "max_pages_per_keyword": 1})}["8433015"]
    assert ad["company"] == ""
    assert ad["location"] == "75 - Paris 19e Arrondissement"


@responses.activate
def test_english_titled_ads_come_through_with_the_french_ones():
    _serve_search("software engineer", pages=("search_english.html",))
    _serve_details(["8413170", "215TSVJ", "8296119", "8186656"])
    out = francetravail.scrape({**_CFG, "search_keywords": ["software engineer"], "topic_terms": ["software*"], "max_pages_per_keyword": 1})
    by_id = {p["platform_id"]: p for p in out}
    assert [p["title"] for p in out] == [
        "Senior Software Engineer - Foodtech H/F", "Software Engineer Web H/F (H/F)",
        "Software Development Engineer in Test (SDET) - Freelance (H/F)", "Software Engineer Python - ai H/F",
    ]
    assert "As a senior engineer you will design" in by_id["8413170"]["description"]
    assert "recherche un profil" in by_id["215TSVJ"]["description"]


@responses.activate
def test_known_ids_cost_no_description_request():
    _serve_search()
    known = frozenset({"8441867", "8433708"})
    _serve_details([i for i in _ALL if i not in known])

    out = francetravail.scrape(_CFG, known_ids=known)

    assert [p["platform_id"] for p in out if p.get("seen_only")] == ["8441867", "8433708"]
    assert not any(u.endswith("/8441867") or u.endswith("/8433708") for u in _requested())
    assert len([p for p in out if not p.get("seen_only")]) == len(_ALL) - 2


@responses.activate
def test_a_page_without_a_next_link_ends_the_keyword_and_a_page_cap_bounds_it():
    _serve(_url("chef de projet", 1), _html("search_short.html"))
    _serve_details(["8444512", "8437319", "8431949"])
    francetravail.scrape({**_CFG, "topic_terms": ["chef de projet*", "pmo", "responsable de projet*"]})
    assert _searches() == [_url("chef de projet", 1)]

    responses.reset()
    _serve_search()
    _serve_details(_PAGE1)
    francetravail.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert _searches() == [_url("chef de projet", 1)]


@responses.activate
def test_an_empty_answer_ends_the_keyword_quietly():
    _serve(_url("native english", 1), _html("search_empty.html"))
    drain_errors()
    drain_answered("francetravail")
    assert francetravail.scrape({**_CFG, "search_keywords": ["native english"]}) == []
    assert drain_errors() == {}
    assert drain_answered("francetravail") is True
    assert _requested() == [_url("native english", 1)]


@responses.activate
def test_two_keywords_dedup_across_them():
    _serve_search("chef de projet", pages=("search_page1.html",))
    _serve_search("chef projet", pages=("search_page1.html",))
    _serve_details(_PAGE1)
    out = francetravail.scrape({**_CFG, "search_keywords": ["chef de projet", "chef projet"], "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == _PAGE1


@responses.activate
def test_role_targets_are_the_fallback_keywords():
    _serve(_url("chef de projet", 1), _html("search_empty.html"))
    cfg = {"role_targets": ["chef de projet"], "location": "Paris"}
    assert francetravail.scrape(cfg) == []
    assert _requested() == [_url("chef de projet", 1)]


@responses.activate
def test_location_and_since_shape_the_search():
    _serve(_url("comptable", 1, code="69123", emission=7), _html("search_empty.html"))
    cfg = {"search_keywords": ["comptable"], "location": "Lyon"}
    francetravail.scrape(cfg, since=datetime.now() - timedelta(days=5))
    assert _requested() == [_url("comptable", 1, code="69123", emission=7)]

    responses.reset()
    _serve(_url("comptable", 1, code=None), _html("search_empty.html"))
    francetravail.scrape({"search_keywords": ["comptable"], "location": "Quimper"})
    assert _requested() == [_url("comptable", 1, code=None)]
    assert "lieux" not in _requested()[0]


@responses.activate
def test_a_failed_description_request_is_recorded_and_the_rest_kept():
    _serve_search(pages=("search_page1.html",))
    _serve_details([i for i in _PAGE1 if i != "8441811"])
    _serve(francetravail._detail_url("8441811"), "boom", status=500)

    drain_errors()
    out = francetravail.scrape({**_CFG, "max_pages_per_keyword": 1})

    assert [p["platform_id"] for p in out] == [i for i in _PAGE1 if i != "8441811"]
    assert any("8441811" in e for e in drain_errors()["francetravail"])
    assert drain_pushback("francetravail") is False


@responses.activate
def test_an_ad_that_is_gone_is_recorded_not_raised():
    _serve_search(pages=("search_page1.html",))
    _serve_details([i for i in _PAGE1 if i != "8450510"])
    _serve(francetravail._detail_url("8450510"), "", status=204)
    drain_errors()
    out = francetravail.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert "8450510" not in [p["platform_id"] for p in out]
    assert any("8450510" in e for e in drain_errors()["francetravail"])


@responses.activate
def test_a_connection_error_is_recorded_not_raised():
    _serve(_url("chef de projet", 1), body=requests.exceptions.ConnectionError("down"))
    drain_errors()
    assert francetravail.scrape(_CFG) == []
    [error] = drain_errors()["francetravail"]
    assert "chef de projet" in error
    assert drain_pushback("francetravail") is False


@responses.activate
def test_a_page_that_is_not_a_result_list_is_recorded_as_a_change():
    _serve(_url("chef de projet", 1), "<html><body><p>Service indisponible</p></body></html>")
    drain_errors()
    drain_answered("francetravail")
    assert francetravail.scrape(_CFG) == []
    assert any("result list" in e for e in drain_errors()["francetravail"])
    assert drain_answered("francetravail") is False


@pytest.mark.parametrize("status", [403, 429])
@responses.activate
def test_a_refusal_on_a_search_page_is_pushback_and_stops_the_run(status):
    _serve(_url("chef de projet", 1), "Access denied", status=status)
    drain_errors()
    drain_pushback("francetravail")

    assert francetravail.scrape({**_CFG, "search_keywords": ["chef de projet", "comptable"]}) == []

    assert drain_pushback("francetravail") is True
    assert "francetravail" in drain_errors()
    assert not any("comptable" in u for u in _requested())  # the run stopped: no second keyword


@responses.activate
def test_a_refusal_on_a_description_keeps_what_was_read_and_stops():
    _serve_search(pages=("search_page1.html",))
    _serve_details(["8441867"])
    _serve(francetravail._detail_url("8441811"), "slow down", status=429)
    drain_errors()
    drain_pushback("francetravail")

    out = francetravail.scrape({**_CFG, "max_pages_per_keyword": 1})

    assert [p["platform_id"] for p in out] == ["8441867"]
    assert drain_pushback("francetravail") is True
    assert not any(u.endswith("/8433015") for u in _requested())


@pytest.mark.usefixtures("obey_robots")
@pytest.mark.real_robots
@responses.activate
def test_a_page_robots_disallows_is_never_loaded():
    responses.add(responses.GET, "https://candidat.francetravail.fr/robots.txt", body="User-agent: *\nDisallow: /offres/\n")
    drain_errors()
    assert francetravail.scrape(_CFG) == []
    assert _requested() == ["https://candidat.francetravail.fr/robots.txt"]
    assert any("robots.txt disallows" in e for e in drain_errors()["francetravail"])


# --- probe ---------------------------------------------------------------------------------------

def _probe_url() -> str:
    return _url("chef de projet", 1)


@responses.activate
def test_probe_ok_maps_the_cards_without_description_requests():
    _serve(_probe_url(), _html("search_page1.html"))
    drain_errors()
    result = francetravail.probe(_CFG)
    assert result["structure_ok"] is True and result["ext"] == "html"
    assert len(result["postings"]) == 4
    for p in result["postings"]:
        JobPosting.model_validate(p)
    assert _requested() == [_probe_url()]
    assert "result-list" in result["raw"]
    assert drain_errors() == {}


@responses.activate
def test_probe_empty_answer_is_ok():
    _serve(_probe_url(), _html("search_empty.html"))
    result = francetravail.probe(_CFG)
    assert result["structure_ok"] is True and result["postings"] == []


@responses.activate
def test_probe_drift_when_the_results_block_is_gone():
    _serve(_probe_url(), "<html><head><title>France Travail</title></head><body><p>Nous revenons vite.</p></body></html>")
    result = francetravail.probe(_CFG)
    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")


@pytest.mark.parametrize("status", [401, 403, 429])
@responses.activate
def test_probe_refusal_is_a_wall(status):
    _serve(_probe_url(), "Access denied", status=status)
    assert francetravail.probe(_CFG)["wall"] is True


@responses.activate
def test_probe_connection_error_is_unreachable():
    _serve(_probe_url(), body=requests.exceptions.ConnectionError("down"))
    assert francetravail.probe(_CFG)["unreachable"] is True


def test_probe_without_keywords_is_none():
    assert francetravail.probe({"location": "Paris"}) is None
