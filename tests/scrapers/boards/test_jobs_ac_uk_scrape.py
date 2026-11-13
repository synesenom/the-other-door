"""Fixture tests for the full jobs.ac.uk scrape() path (server-rendered search pages, schema.org ad pages).

HTTP is mocked with `responses` from pages saved from the live site (search "research associate", the
London location facet, newest first, pages 1 and 2 trimmed to three ads each with the count set to 30 so
that page 2 is the last; one ad page with its JobPosting JSON-LD, text rewritten). No network.
"""

from datetime import date, datetime
from pathlib import Path

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_answered, drain_errors, drain_pushback
from door.scrapers.boards import jobs_ac_uk

_FIX = Path(__file__).parent / "fixtures" / "jobs_ac_uk"
_CFG = {"search_keywords": ["research associate"], "topic_terms": ["postdoc*", "research*", "lecturer*"], "location": "London"}
_PAGE1 = ["1093148", "1093143", "1093009"]
_PAGE2 = ["1092420", "1092388"]  # 1092425 (Clinical Project Manager) is off topic
_PATHS = {
    "1093148": "/job/DTN132/postdoctoral-research-associate",
    "1093143": "/job/DTN118/postdoctoral-research-associate",
    "1093009": "/job/DTM716/senior-lecturer-in-organisations-work-and-digital-transformation",
    "1092420": "/job/DTK887/postdoctoral-research-associate-in-gpu-les-and-aeroacoustics",
    "1092425": "/job/DTK909/clinical-project-manager-in-neuropsychopharmacology-and-experimental-medicine",
    "1092388": "/job/DTK835/postdoctoral-research-associate",
}


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr(jobs_ac_uk, "_today", lambda: date(2026, 11, 3))


def _serve(url: str, body: str | None = None, **kw) -> None:
    responses.add(responses.GET, url, body=body, **kw)


def _search(keyword: str = "research associate", page: int = 1, location: str = "London") -> str:
    return jobs_ac_uk._search_url(keyword, location, page)


def _serve_search(pages=("p1.html", "p2.html"), keyword: str = "research associate") -> None:
    for n, name in enumerate(pages, 1):
        _serve(_search(keyword, n), _html(name))


def _serve_details(ids) -> None:
    for i in ids:
        _serve("https://www.jobs.ac.uk" + _PATHS[i], _html("detail.html"))


def _requested() -> list[str]:
    return [c.request.url for c in responses.calls]


def _searches() -> list[str]:
    return [u for u in _requested() if "/search/" in u]


@responses.activate
def test_scrape_paginates_and_reads_the_ads():
    _serve_search()
    _serve_details(_PAGE1 + _PAGE2)
    drain_errors()
    postings = jobs_ac_uk.scrape(_CFG)

    assert [p["platform_id"] for p in postings] == _PAGE1 + _PAGE2
    assert drain_errors() == {}
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "jobs_ac_uk" and p["id"] == f"jobs_ac_uk.{p['platform_id']}"
        assert p["title"] and p["company"] and p["url"] and p["location"]
        assert p["description"].startswith("Location: Mile End Road") and "<" not in p["description"]
        assert p["url"] == "https://www.jobs.ac.uk" + _PATHS[p["platform_id"]]
    assert _searches() == [_search(page=1), _search(page=2)]
    assert len(_requested()) == 2 + 5  # two search pages, five on-topic ads; page 2 was the last (no Next link)


@responses.activate
def test_card_fields_and_the_ad_date_map_to_the_posting():
    _serve_search(("p1.html",))
    _serve_details(_PAGE1)
    by_id = {p["platform_id"]: p for p in jobs_ac_uk.scrape({**_CFG, "max_pages_per_keyword": 1})}
    p = by_id["1093148"]
    assert p["title"] == "Postdoctoral Research Associate" and p["company"] == "Queen Mary University of London"
    assert p["location"] == "London" and p["posted_at"].startswith("2026-11-03")
    assert by_id["1093009"]["company"] == "University of Salford"


@responses.activate
def test_posted_date_falls_back_to_the_card_with_its_inferred_year():
    _serve_search(("p2.html",))
    _serve("https://www.jobs.ac.uk" + _PATHS["1092420"], "<html>no data</html>")
    _serve_details(["1092388"])
    out = jobs_ac_uk.scrape({**_CFG, "max_pages_per_keyword": 1}, since=None)
    # page 2 of the saved search is read first here (p2.html as the only page): "27 Oct" is this year
    assert out[0]["posted_at"].startswith("2026-10-27")


@responses.activate
def test_known_ids_cost_no_ad_request():
    _serve_search()
    known = frozenset({"1093148", "1092388"})
    _serve_details([i for i in _PAGE1 + _PAGE2 if i not in known])
    out = jobs_ac_uk.scrape(_CFG, known_ids=known)
    assert [p["platform_id"] for p in out if p.get("seen_only")] == ["1093148", "1092388"]
    assert not any("DTN132" in u or "DTK835" in u for u in _requested())
    assert len([p for p in out if not p.get("seen_only")]) == 3


@responses.activate
def test_off_topic_titles_cost_no_ad_request():
    _serve_search(("p1.html", "p2.html"))
    _serve_details(_PAGE1 + _PAGE2)
    jobs_ac_uk.scrape(_CFG)
    assert not any("DTK909" in u for u in _requested())


@responses.activate
def test_cards_in_another_place_cost_no_ad_request():
    body = _html("p1.html").replace("Location:\n            London", "Location:\n            Glasgow", 1)
    assert "Glasgow" in body
    _serve(_search(), body)
    _serve_details(["1093143", "1093009"])
    out = jobs_ac_uk.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == ["1093143", "1093009"]
    assert not any("DTN132" in u for u in _requested())


@responses.activate
def test_cards_in_the_commute_area_stay():
    body = _html("p1.html").replace("Location:\n            London", "Location:\n            Guildford", 1)
    _serve(_search(), body)
    _serve_details(_PAGE1)
    out = jobs_ac_uk.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == _PAGE1


@responses.activate
def test_since_ends_the_keyword_at_the_first_older_ad():
    _serve_search()
    _serve_details(["1093148", "1093143"])
    out = jobs_ac_uk.scrape(_CFG, since=datetime(2026, 11, 3))
    assert [p["platform_id"] for p in out] == ["1093148", "1093143"]  # 1093009 was placed on 2 Nov
    assert _searches() == [_search(page=1)]  # newest first: nothing on page 2 can be newer


@responses.activate
def test_a_page_cap_bounds_the_keyword():
    _serve_search(("p1.html",))
    _serve_details(_PAGE1)
    jobs_ac_uk.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert _searches() == [_search(page=1)]


@responses.activate
def test_an_empty_page_ends_the_keyword_quietly():
    _serve(_search(), '<html><h2 class="j-search-content__count"><strong class="job-count">0 </strong> Jobs Found</h2></html>')
    drain_errors()
    drain_answered("jobs_ac_uk")
    assert jobs_ac_uk.scrape(_CFG) == []
    assert drain_errors() == {}
    assert drain_answered("jobs_ac_uk") is True
    assert _requested() == [_search()]


@responses.activate
def test_a_page_without_results_block_is_recorded():
    _serve(_search(), "<html><body>Something else</body></html>")
    drain_errors()
    drain_answered("jobs_ac_uk")
    assert jobs_ac_uk.scrape(_CFG) == []
    assert "jobs_ac_uk" in drain_errors()
    assert drain_answered("jobs_ac_uk") is False


@responses.activate
def test_a_real_zero_hit_page_is_an_answer():
    _serve(_search(), _html("search_empty.html"))
    drain_errors()
    drain_answered("jobs_ac_uk")
    assert jobs_ac_uk.scrape(_CFG) == []
    assert drain_errors() == {}
    assert drain_answered("jobs_ac_uk") is True


@responses.activate
def test_two_keywords_dedup_across_them():
    _serve(_search("research associate"), _html("p1.html"))
    _serve(_search("postdoc"), _html("p1.html"))
    _serve_details(_PAGE1)
    out = jobs_ac_uk.scrape({**_CFG, "search_keywords": ["research associate", "postdoc"], "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == _PAGE1


@responses.activate
def test_role_targets_are_the_fallback_keywords():
    _serve(_search(), '<html><h2 class="j-search-content__count"><strong class="job-count">0</strong> Jobs Found</h2></html>')
    assert jobs_ac_uk.scrape({"role_targets": ["research associate"], "location": "London"}) == []
    assert _requested() == [_search()]


@responses.activate
def test_a_failed_ad_request_is_recorded_and_the_card_kept():
    _serve_search(("p1.html",))
    _serve_details(["1093148", "1093009"])
    _serve("https://www.jobs.ac.uk" + _PATHS["1093143"], "boom", status=500)
    drain_errors()
    out = jobs_ac_uk.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == _PAGE1
    assert out[1]["description"] and "School of Physical and Chemical Sciences" in out[1]["description"]
    assert any("1093143" in e or "DTN118" in e for e in drain_errors()["jobs_ac_uk"])
    assert drain_pushback("jobs_ac_uk") is False


@responses.activate
def test_an_ad_without_json_ld_is_recorded_and_the_card_kept():
    _serve_search(("p1.html",))
    _serve_details(["1093148", "1093009"])
    _serve("https://www.jobs.ac.uk" + _PATHS["1093143"], "<html><body>no data</body></html>")
    drain_errors()
    out = jobs_ac_uk.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert len(out) == 3 and out[1]["description"]
    assert any("DTN118" in e for e in drain_errors()["jobs_ac_uk"])


@responses.activate
def test_a_connection_error_is_recorded_not_raised():
    _serve(_search(), body=requests.exceptions.ConnectionError("down"))
    drain_errors()
    assert jobs_ac_uk.scrape(_CFG) == []
    [error] = drain_errors()["jobs_ac_uk"]
    assert "research associate" in error
    assert drain_pushback("jobs_ac_uk") is False


@pytest.mark.parametrize("status", [403, 429])
@responses.activate
def test_a_refusal_on_a_search_page_is_pushback_and_stops_the_run(status):
    _serve(_search(), "Access denied", status=status)
    drain_errors()
    drain_pushback("jobs_ac_uk")
    assert jobs_ac_uk.scrape({**_CFG, "search_keywords": ["research associate", "postdoc"]}) == []
    assert drain_pushback("jobs_ac_uk") is True
    assert "jobs_ac_uk" in drain_errors()
    assert not any("postdoc" in u for u in _requested())


@responses.activate
def test_a_challenge_page_with_status_200_is_pushback_too():
    _serve(_search(), "<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/h/b'></script></html>")
    drain_errors()
    drain_pushback("jobs_ac_uk")
    assert jobs_ac_uk.scrape(_CFG) == []
    assert drain_pushback("jobs_ac_uk") is True


@responses.activate
def test_a_refusal_on_an_ad_keeps_what_was_read_and_stops():
    _serve_search(("p1.html",))
    _serve_details(["1093148"])
    _serve("https://www.jobs.ac.uk" + _PATHS["1093143"], "slow down", status=429)
    drain_errors()
    drain_pushback("jobs_ac_uk")
    out = jobs_ac_uk.scrape({**_CFG, "max_pages_per_keyword": 1})
    assert [p["platform_id"] for p in out] == ["1093148"]
    assert drain_pushback("jobs_ac_uk") is True
    assert not any("DTM716" in u for u in _requested())


# --- probe ---------------------------------------------------------------------------------------

@responses.activate
def test_probe_ok_maps_the_cards_without_ad_requests():
    _serve(_search(), _html("p1.html"))
    drain_errors()
    result = jobs_ac_uk.probe(_CFG)
    assert result["structure_ok"] is True and result["ext"] == "html"
    assert len(result["postings"]) == 3
    for p in result["postings"]:
        JobPosting.model_validate(p)
    assert _requested() == [_search()]
    assert drain_errors() == {}


@responses.activate
def test_probe_drift_when_the_results_block_is_removed():
    _serve(_search(), _html("p1.html").replace("j-search-result__result", "gone").replace("job-count", "gone"))
    result = jobs_ac_uk.probe(_CFG)
    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")


@pytest.mark.parametrize("status", [401, 403, 429])
@responses.activate
def test_probe_refusal_is_a_wall(status):
    _serve(_search(), "Just a moment...", status=status)
    assert jobs_ac_uk.probe(_CFG)["wall"] is True


@responses.activate
def test_probe_challenge_page_is_a_wall():
    _serve(_search(), "<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/h/b'></script></html>")
    result = jobs_ac_uk.probe(_CFG)
    assert result["wall"] is True and result["structure_ok"] is False


@responses.activate
def test_probe_connection_error_is_unreachable():
    _serve(_search(), body=requests.exceptions.ConnectionError("down"))
    assert jobs_ac_uk.probe(_CFG)["unreachable"] is True


def test_probe_without_keywords_is_none():
    assert jobs_ac_uk.probe({"location": "London"}) is None
