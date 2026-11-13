"""Fixture tests for the full Globalnyt scrape() path: the WordPress list, then one detail page per new ad."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import responses

from door.core.models import JobPosting
from door.scrapers import drain_answered, drain_errors
from door.scrapers.boards import globalnyt

_FIX = Path(__file__).parent / "fixtures" / "globalnyt"
_CFG = {"search_keywords": ["programme advisor"], "location": "Copenhagen"}
_BASE = "https://globalnyt.dk/stilling/"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    drain_errors("globalnyt"), drain_answered("globalnyt")


def _text(name):
    return (_FIX / name).read_text(encoding="utf-8")


def _serve(details=True):
    responses.add(responses.GET, globalnyt._LIST_URL, body=_text("stilling_list.json"), content_type="application/json")
    if details:
        responses.add(responses.GET, _BASE + "mhpss-advisor/", body=_text("detail_mhpss.html"))
        responses.add(responses.GET, _BASE + "maternity-cover-partnership-manager/", body=_text("detail_oxfam.html"))
        responses.add(responses.GET, _BASE + "head-of-programmes-ukraine/", body=_text("detail_noorg.html"))
        responses.add(responses.GET, _BASE + "universitetspraktikant/", body=_text("detail_oxfam.html"))


@responses.activate
def test_every_ad_is_returned_with_its_employer_from_the_detail_page():
    _serve()
    postings = globalnyt.scrape(_CFG)
    by_id = {p["platform_id"]: p for p in postings}
    assert set(by_id) == {"510393", "510291", "508636", "456923"}
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "globalnyt" and p["id"] == f"globalnyt.{p['platform_id']}"
    assert by_id["510393"]["company"] == "Røde Kors" and by_id["510393"]["location"] == "København"
    assert by_id["510291"]["company"] == "Oxfam Denmark" and by_id["510291"]["location"] == ""
    assert by_id["510393"]["url"] == _BASE + "mhpss-advisor/"
    assert by_id["510393"]["description"]


@responses.activate
def test_a_known_ad_costs_no_detail_request_and_an_old_one_is_skipped():
    _serve()
    since = datetime(2026, 10, 1, tzinfo=timezone.utc)
    postings = globalnyt.scrape(_CFG, known_ids=frozenset({"510393"}), since=since)
    assert {p["platform_id"] for p in postings} == {"510291", "508636"}
    assert not any("mhpss-advisor" in c.request.url for c in responses.calls)
    assert not any("universitetspraktikant" in c.request.url for c in responses.calls)


@responses.activate
def test_an_ad_whose_page_names_no_employer_still_comes_back_under_the_board_name():
    _serve()
    ukraine = next(p for p in globalnyt.scrape(_CFG) if p["platform_id"] == "508636")
    assert ukraine["company"] == "Globalnyt"


@responses.activate
def test_a_failing_detail_page_is_recorded_and_the_ad_kept():
    _serve(details=False)
    responses.add(responses.GET, _BASE + "mhpss-advisor/", status=500)
    for slug in ("maternity-cover-partnership-manager", "head-of-programmes-ukraine", "universitetspraktikant"):
        responses.add(responses.GET, _BASE + slug + "/", body=_text("detail_oxfam.html"))
    postings = globalnyt.scrape(_CFG)
    assert len(postings) == 4
    assert drain_errors("globalnyt").get("globalnyt")


@responses.activate
def test_a_failing_list_is_an_error():
    responses.add(responses.GET, globalnyt._LIST_URL, status=500)
    assert globalnyt.scrape(_CFG) == []
    assert drain_errors("globalnyt").get("globalnyt")
    assert drain_answered("globalnyt") is False


@responses.activate
def test_an_empty_list_is_a_quiet_day():
    responses.add(responses.GET, globalnyt._LIST_URL, body=_text("stilling_list_empty.json"), content_type="application/json")
    assert globalnyt.scrape(_CFG) == []
    assert not drain_errors("globalnyt").get("globalnyt")
    assert drain_answered("globalnyt") is True


@responses.activate
def test_probe_reads_the_list_without_detail_requests():
    _serve(details=False)
    result = globalnyt.probe(_CFG)
    assert result["structure_ok"] and len(result["postings"]) == 4
    assert len(responses.calls) == 1
