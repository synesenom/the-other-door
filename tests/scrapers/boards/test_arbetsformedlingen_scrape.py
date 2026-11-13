"""Fixture tests for the full Arbetsförmedlingen scrape() path: the JobSearch API, HTTP mocked with `responses` from
saved answers (trimmed to what the parser reads, the ad texts rewritten)."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_answered, drain_errors, drain_pushback
from door.scrapers.boards import arbetsformedlingen as af

_FIX = Path(__file__).parent / "fixtures" / "arbetsformedlingen"
_CFG = {"search_keywords": ["project manager"], "role_targets": ["Projektledare"], "location": "Stockholm"}
_SEARCH = re.compile(r"https://jobsearch\.api\.jobtechdev\.se/search\?.*")


def _text(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _small_pages(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr(af, "_PAGE_SIZE", 4)   # the saved first page holds four ads
    drain_errors(), drain_pushback("arbetsformedlingen"), drain_answered("arbetsformedlingen")


def _serve_pages(*, pages=("search_page1.json", "search_page2.json")):
    """Answer by the `offset` of the request: page n for offset n*4, the empty answer after."""
    def callback(request):
        offset = int(parse_qs(urlparse(request.url).query).get("offset", ["0"])[0])
        index = offset // 4
        return 200, {}, _text(pages[index] if index < len(pages) else "empty.json")
    responses.add_callback(responses.GET, _SEARCH, callback=callback, content_type="application/json")


def _queries():
    return [parse_qs(urlparse(c.request.url).query) for c in responses.calls]


@responses.activate
def test_two_pages_become_postings_in_english_and_swedish():
    _serve_pages()
    postings = af.scrape(_CFG)
    assert [p["platform_id"] for p in postings] == [
        "31668014", "31666374", "31632735", "31632254", "31629624", "31615801", "31597903"]
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
        assert p["location"] == "Stockholm" and p["posted_at"]
    by_id = {p["platform_id"]: p for p in postings}
    assert by_id["31666374"]["description"].startswith("Project Manager, Sweden")        # English
    assert by_id["31632735"]["title"] == "ASSA ABLOY söker Senior Project Manager"      # Swedish
    assert by_id["31632735"]["description"].startswith("Vill du leda")
    assert by_id["31632735"]["company"] == "ASSA ABLOY Entrance Systems Pedestrian AB"
    assert len(responses.calls) == 2   # a short second page ends the keyword


@responses.activate
def test_the_request_names_the_keyword_the_municipalities_and_the_page():
    _serve_pages()
    af.scrape(_CFG)
    first, second = _queries()
    assert first["q"] == ["project manager"] and first["offset"] == ["0"] and first["limit"] == ["4"]
    assert first["municipality"][0] == "AvNB_uwa_6n6"
    assert first["sort"] == ["pubdate-desc"]
    assert second["offset"] == ["4"]
    assert "published-after" not in first


@responses.activate
def test_the_keyword_is_sent_as_it_is_with_no_language_filter():
    _serve_pages(pages=("empty.json",))
    af.scrape({**_CFG, "search_keywords": ["projektledare"]})
    [query] = _queries()
    assert query["q"] == ["projektledare"]
    assert not {"language", "lang"} & set(query)


@responses.activate
def test_known_ids_since_and_repeats_are_skipped():
    _serve_pages()
    since = datetime(2026, 10, 22, 16, 0, tzinfo=timezone.utc)
    postings = af.scrape(_CFG, known_ids=frozenset({"31668014"}), since=since)
    # not the known one; not the ones published before 22 Oct 18:00 Stockholm time (31632254 at 13:46, 31632735 at 14:41 local)
    assert [p["platform_id"] for p in postings] == ["31666374"]
    assert _queries()[0]["published-after"] == ["2026-10-22T18:00:00"]


@responses.activate
def test_an_ad_in_two_keywords_counts_once():
    _serve_pages(pages=("search_page2.json",) * 2)
    postings = af.scrape({**_CFG, "search_keywords": ["a", "b"]})
    assert len(postings) == 3 and len(responses.calls) == 2


@responses.activate
def test_a_removed_ad_is_dropped():
    page = json.loads(_text("search_page2.json"))
    page["hits"][0]["removed"] = True
    responses.add(responses.GET, _SEARCH, json=page)
    assert [p["platform_id"] for p in af.scrape(_CFG)] == ["31615801", "31597903"]


@responses.activate
def test_a_failed_request_is_recorded_and_the_next_keyword_still_runs():
    responses.add(responses.GET, _SEARCH, status=500)
    responses.add(responses.GET, _SEARCH, status=500)
    responses.add(responses.GET, _SEARCH, status=500)
    responses.add(responses.GET, _SEARCH, status=500)
    responses.add(responses.GET, _SEARCH, body=_text("search_page2.json"), content_type="application/json")
    cfg = {**_CFG, "search_keywords": ["first", "second"]}
    postings = af.scrape(cfg)
    assert len(postings) == 3
    [error] = drain_errors()["arbetsformedlingen"]
    assert "first" in error
    assert drain_answered("arbetsformedlingen") is False
    assert drain_pushback("arbetsformedlingen") is False


@responses.activate
def test_a_connection_error_is_recorded_not_raised():
    responses.add(responses.GET, _SEARCH, body=requests.exceptions.ConnectionError("down"))
    assert af.scrape(_CFG) == []
    assert "project manager" in drain_errors()["arbetsformedlingen"][0]


@responses.activate
def test_a_certificate_failure_says_what_to_do():
    responses.add(responses.GET, _SEARCH, body=requests.exceptions.SSLError("self signed certificate in certificate chain"))
    assert af.scrape(_CFG) == []
    message = drain_errors()["arbetsformedlingen"][0]
    assert "certificate" in message.lower() and "Telia" in message


@responses.activate
def test_an_answer_that_is_not_json_is_an_error():
    responses.add(responses.GET, _SEARCH, body="<html>maintenance</html>")
    assert af.scrape(_CFG) == []
    assert drain_errors()["arbetsformedlingen"]


@pytest.mark.parametrize("status", [403, 429])
@responses.activate
def test_a_refusal_is_pushback_and_stops_the_run(status):
    responses.add(responses.GET, _SEARCH, body="no", status=status)
    assert af.scrape({**_CFG, "search_keywords": ["first", "second"]}) == []
    assert drain_pushback("arbetsformedlingen") is True
    assert drain_errors()["arbetsformedlingen"]
    assert not any("second" in c.request.url for c in responses.calls)


@responses.activate
def test_an_empty_answer_is_quiet():
    _serve_pages(pages=("empty.json",))
    assert af.scrape(_CFG) == []
    assert not drain_errors().get("arbetsformedlingen")
    assert drain_answered("arbetsformedlingen") is True


@responses.activate
def test_a_profile_without_keywords_falls_back_to_role_targets():
    _serve_pages(pages=("empty.json",))
    af.scrape({"role_targets": ["Projektledare"], "location": "Stockholm"})
    assert _queries()[0]["q"] == ["Projektledare"]


@responses.activate
def test_probe_reads_the_first_page_with_one_request():
    _serve_pages()
    result = af.probe(_CFG)
    assert result["structure_ok"] and len(result["postings"]) == 4 and result["ext"] == "json"
    assert len(responses.calls) == 1 and _queries()[0]["q"] == ["project manager"]
    assert drain_errors() == {}


@responses.activate
def test_probe_drift_when_the_hits_are_gone():
    page = json.loads(_text("search_page1.json"))
    del page["hits"]
    responses.add(responses.GET, _SEARCH, json=page)
    result = af.probe(_CFG)
    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")


@pytest.mark.parametrize("status", [401, 403, 429])
@responses.activate
def test_probe_refusal_is_a_wall(status):
    responses.add(responses.GET, _SEARCH, body="no", status=status)
    assert af.probe(_CFG)["wall"] is True


@responses.activate
def test_probe_connection_error_is_unreachable():
    responses.add(responses.GET, _SEARCH, body=requests.exceptions.ConnectionError("down"))
    assert af.probe(_CFG)["unreachable"] is True


@responses.activate
def test_probe_certificate_failure_is_unreachable_with_a_clear_reason():
    responses.add(responses.GET, _SEARCH, body=requests.exceptions.SSLError("self signed certificate in certificate chain"))
    result = af.probe(_CFG)
    assert result["unreachable"] is True and "Telia" in result["reason"]
    assert drain_errors() == {}


def test_probe_without_keywords_is_none():
    assert af.probe({"location": "Stockholm"}) is None
