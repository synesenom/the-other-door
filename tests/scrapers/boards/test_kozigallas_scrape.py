"""Fixture tests for the full KÖZSZOLGÁLLÁS scrape() path (kozszolgallas.ksz.gov.hu, plain HTTP).

HTTP is mocked with `responses` from pages saved from the live portal (a search for "ápoló": result lists
posted to ``/JobAd/ListGridAsync``, ad pages from ``/JobAd/Info/<id>``; free text rewritten): two result pages
(the portal's page size is patched to 3 to match the trimmed pages), an empty answer. The portal's ads
are all Hungarian. No network.
"""

import json
from pathlib import Path

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_answered, drain_errors, drain_pushback
from door.scrapers.boards import kozigallas

_FIX = Path(__file__).parent / "fixtures" / "kozigallas"
_BASE = "https://kozszolgallas.ksz.gov.hu"
_LIST = _BASE + "/JobAd/ListGridAsync"
_CFG = {"search_keywords": ["ápoló"], "topic_terms": ["*ápoló*", "*ápolói*"], "location": "Budapest"}
_PAGE1 = ["175084", "175074", "175065"]
_PAGE2 = ["174786"]  # its second card, 175084 again, is a duplicate
_ALL = _PAGE1 + _PAGE2


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _small_pages(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr(kozigallas, "_PAGE_SIZE", 3)


def _serve_list(pages: dict[str, dict[int, str]] | None = None, *, default: dict[int, str] | None = None) -> None:
    """Answer the list POST by the body's keyword and page."""
    pages = pages or {"ápoló": default or {1: "list_p1.html", 2: "list_p2.html"}}

    def answer(request):
        body = json.loads(request.body)
        name = pages.get(body["keyword"], {}).get(body["page"])
        return (200, {}, _html(name) if name else _html("list_empty.html"))

    responses.add_callback(responses.POST, _LIST, callback=answer, content_type="text/html")


def _serve_details(ids) -> None:
    for i in ids:
        responses.add(responses.GET, f"{_BASE}/JobAd/Info/{i}", body=_html(f"detail_{i}.html"))


def _requested() -> list[str]:
    return [c.request.url for c in responses.calls]


def _searches() -> list[dict]:
    return [json.loads(c.request.body) for c in responses.calls if c.request.url == _LIST]


@responses.activate
def test_scrape_paginates_dedups_and_reads_the_ads():
    _serve_list()
    _serve_details(_ALL)

    drain_errors()
    postings = kozigallas.scrape(_CFG)

    assert [p["platform_id"] for p in postings] == _ALL
    assert drain_errors() == {}
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "kozigallas"
        assert p["id"] == f"kozigallas.{p['platform_id']}"
        assert p["title"] and p["company"] and p["url"] and p["description"]
        assert p["url"] == f"{_BASE}/JobAd/Info/{p['platform_id']}"
    # Two list pages and one ad page per distinct ad; the duplicate card costs nothing.
    assert len(_requested()) == 2 + len(_ALL)
    assert [s["page"] for s in _searches()] == [1, 2]
    assert all(s["keyword"] == "ápoló" for s in _searches())


@responses.activate
def test_mapping_of_an_ad():
    _serve_list()
    _serve_details(_ALL)
    by_id = {p["platform_id"]: p for p in kozigallas.scrape(_CFG)}

    ad = by_id["175084"]
    assert ad["title"] == "ápoló/szakápoló"
    assert ad["company"].startswith("SZOLNOKI KISTÉRSÉG")
    assert ad["location"] == "Rákóczifalva"
    assert ad["posted_at"].startswith("2026-11-11")
    assert "Az ellátottak egészségi állapotának" in ad["description"]
    assert by_id["174786"]["title"] == "Kollégiumi ápoló"
    assert by_id["174786"]["location"] == "Budapest"
    # An ad with no publication date still has a posting, undated.
    assert by_id["175065"]["posted_at"] is None


@responses.activate
def test_off_topic_cards_cost_no_ad_request():
    _serve_list({"mérnök": {1: "list_p1.html"}})
    _serve_details(_PAGE1)
    out = kozigallas.scrape({**_CFG, "search_keywords": ["mérnök"], "topic_terms": ["mérnök*"], "max_pages_per_keyword": 1})
    assert out == []
    assert _requested() == [_LIST]


@responses.activate
def test_known_ids_cost_no_ad_request():
    _serve_list()
    known = frozenset({"175084", "174786"})
    _serve_details([i for i in _ALL if i not in known])

    out = kozigallas.scrape(_CFG, known_ids=known)

    assert sorted(p["platform_id"] for p in out if p.get("seen_only")) == ["174786", "175084"]
    assert f"{_BASE}/JobAd/Info/175084" not in _requested() and f"{_BASE}/JobAd/Info/174786" not in _requested()
    assert len([p for p in out if not p.get("seen_only")]) == 2


@responses.activate
def test_the_page_count_ends_the_keyword_and_a_page_cap_bounds_it():
    _serve_list()
    _serve_details(_ALL)
    kozigallas.scrape(_CFG)
    assert [s["page"] for s in _searches()] == [1, 2]  # the portal says 2 pages: no page 3

    responses.reset()
    _serve_list()
    _serve_details(_PAGE1)
    kozigallas.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert [s["page"] for s in _searches()] == [1]


@responses.activate
def test_an_empty_answer_is_a_quiet_day():
    _serve_list({"zzzxqv": {}})
    drain_errors()
    drain_answered("kozigallas")
    assert kozigallas.scrape({**_CFG, "search_keywords": ["zzzxqv"]}) == []
    assert drain_errors() == {}
    assert drain_answered("kozigallas") is True
    assert _requested() == [_LIST]


@responses.activate
def test_two_keywords_dedup_across_them():
    _serve_list({"ápoló": {1: "list_p1.html"}, "szakápoló": {1: "list_p1.html"}})
    _serve_details(_PAGE1)
    out = kozigallas.scrape({**_CFG, "search_keywords": ["ápoló", "szakápoló"], "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == _PAGE1


@responses.activate
def test_role_targets_are_the_fallback_keywords_and_location_and_since_are_not_sent():
    _serve_list({"ápoló": {}})
    kozigallas.scrape({"role_targets": ["ápoló"], "location": "Budapest"}, since=None)
    assert _searches() == [{"page": 1, "pagesize": 3, "sort": "Created DESC", "keyword": "ápoló"}]


@responses.activate
def test_a_failed_ad_request_is_recorded_and_the_rest_kept():
    _serve_list(default={1: "list_p1.html"})
    _serve_details(["175074", "175065"])
    responses.add(responses.GET, f"{_BASE}/JobAd/Info/175084", body="boom", status=500)

    drain_errors()
    out = kozigallas.scrape({**_CFG, "max_pages_per_keyword": 1})

    assert [p["platform_id"] for p in out] == ["175074", "175065"]
    assert any("175084" in e for e in drain_errors()["kozigallas"])
    assert drain_pushback("kozigallas") is False


@responses.activate
def test_an_ad_page_without_text_is_recorded_not_raised():
    _serve_list(default={1: "list_p1.html"})
    _serve_details(["175074", "175065"])
    responses.add(responses.GET, f"{_BASE}/JobAd/Info/175084", body="<html><body><p>Nem található.</p></body></html>")
    drain_errors()
    out = kozigallas.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == ["175074", "175065"]
    assert any("175084" in e for e in drain_errors()["kozigallas"])


@responses.activate
def test_a_connection_error_is_recorded_not_raised():
    responses.add(responses.POST, _LIST, body=requests.exceptions.ConnectionError("down"))
    drain_errors()
    assert kozigallas.scrape(_CFG) == []
    [error] = drain_errors()["kozigallas"]
    assert "ápoló" in error
    assert drain_pushback("kozigallas") is False


@responses.activate
def test_an_answer_that_is_not_a_result_list_is_recorded_as_a_change():
    responses.add(responses.POST, _LIST, body="<html><body>Hiba történt</body></html>")
    drain_errors()
    drain_answered("kozigallas")
    assert kozigallas.scrape(_CFG) == []
    assert any("result list" in e for e in drain_errors()["kozigallas"])
    assert drain_answered("kozigallas") is False


@pytest.mark.parametrize("status", [403, 429])
@responses.activate
def test_a_refusal_on_a_search_is_pushback_and_stops_the_run(status):
    responses.add(responses.POST, _LIST, body="Access denied", status=status)
    drain_errors()
    drain_pushback("kozigallas")

    assert kozigallas.scrape({**_CFG, "search_keywords": ["ápoló", "szakápoló"]}) == []

    assert drain_pushback("kozigallas") is True
    assert "kozigallas" in drain_errors()
    assert not any(json.loads(c.request.body)["keyword"] == "szakápoló" for c in responses.calls if c.request.method == "POST")


@responses.activate
def test_a_refusal_on_an_ad_keeps_what_was_read_and_stops():
    _serve_list(default={1: "list_p1.html"})
    _serve_details(["175084"])
    responses.add(responses.GET, f"{_BASE}/JobAd/Info/175074", body="slow down", status=429)
    drain_errors()
    drain_pushback("kozigallas")

    out = kozigallas.scrape({**_CFG, "max_pages_per_keyword": 1})

    assert [p["platform_id"] for p in out] == ["175084"]
    assert drain_pushback("kozigallas") is True


@responses.activate
def test_the_session_verifies_against_the_system_trust_store(monkeypatch):
    seen = {}
    real = kozigallas.PoliteSession

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(kozigallas, "PoliteSession", spy)
    _serve_list({"ápoló": {}})
    kozigallas.scrape(_CFG)
    assert seen["system_trust"] is True


# --- probe ---------------------------------------------------------------------------------------

@responses.activate
def test_probe_ok_maps_the_cards_without_ad_requests():
    _serve_list()
    drain_errors()
    result = kozigallas.probe(_CFG)
    assert result["structure_ok"] is True and result["ext"] == "html"
    assert len(result["postings"]) == 3
    for p in result["postings"]:
        JobPosting.model_validate(p)
    assert _requested() == [_LIST]
    assert "jobaditemelement" in result["raw"]
    assert drain_errors() == {}


@responses.activate
def test_probe_empty_answer_is_ok():
    _serve_list({"ápoló": {}})
    result = kozigallas.probe(_CFG)
    assert result["structure_ok"] is True and result["postings"] == []


@responses.activate
def test_probe_drift_when_the_results_block_is_gone():
    html = _html("list_p1.html").replace("jobaditemelement", "other").replace("ListInfo.TotalCount", "Other.Total")
    responses.add(responses.POST, _LIST, body=html)
    result = kozigallas.probe(_CFG)
    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")
    assert drain_errors() == {}


@responses.activate
def test_probe_unreachable_on_a_connection_error():
    responses.add(responses.POST, _LIST, body=requests.exceptions.ConnectionError("down"))
    result = kozigallas.probe(_CFG)
    assert result["unreachable"] is True and result["structure_ok"] is False
    assert len(responses.calls) == 1


@pytest.mark.parametrize("status", [401, 403])
@responses.activate
def test_probe_wall_on_a_refusal(status):
    responses.add(responses.POST, _LIST, body="denied", status=status)
    result = kozigallas.probe(_CFG)
    assert result["wall"] is True and result["structure_ok"] is False
    assert len(responses.calls) == 1


def test_probe_without_keywords_is_none():
    assert kozigallas.probe({"location": "Budapest"}) is None
