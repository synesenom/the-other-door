"""Fixture tests for the Signatur job portal: Helsingør Kommune's live postings, trimmed and their ad text rewritten."""

import pytest
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.feeds import signatur
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "signatur"
_BASE = "https://portal.signatur.dk/ExtJobs/DefaultHosting"
_LIST = f"{_BASE}/JobList.aspx?ClientId=2296"
_IDS = ["166122", "166057"]


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _detail(wid: str) -> str:
    return f"{_BASE}/JobDetails.aspx?ClientId=2296&WebAdId={wid}"


def _mock_all():
    responses.add(responses.GET, _LIST, body=_fx("helsingor_list.html"))
    for wid in _IDS:
        responses.add(responses.GET, _detail(wid), body=_fx(f"helsingor_{wid}.html"))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_maps_every_listed_job():
    _mock_all()

    postings = signatur.scrape({"signatur_companies": ["2296"]})

    assert len(postings) == 2
    first = postings[0]
    JobPosting.model_validate(first)
    assert first["title"].startswith("Administrativ sagsbehandler til Børne- og ungeområdet")
    assert first["company"] == "Helsingør Kommune"
    assert first["platform_id"] == "2296-166122"
    assert first["location"] == "Birkedalsvej 27, 3000, Helsingør, Danmark"
    assert first["url"] == _detail("166122")
    assert first["apply_url"] == first["url"]
    assert "Barnets lov" in first["description"] and "<" not in first["description"]
    assert first["source"] == "signatur"


@responses.activate
def test_known_ids_skip_the_detail_request():
    responses.add(responses.GET, _LIST, body=_fx("helsingor_list.html"))
    responses.add(responses.GET, _detail("166122"), body=_fx("helsingor_166122.html"))

    postings = signatur.scrape({"signatur_companies": ["2296"]}, known_ids=frozenset({"2296-166057"}))

    assert [p["platform_id"] for p in postings if not p.get("seen_only")] == ["2296-166122"]
    assert sorted(p["platform_id"] for p in postings if p.get("seen_only")) == ["2296-166057"]
    assert len(responses.calls) == 2


@responses.activate
def test_a_failing_detail_keeps_the_job_from_the_list():
    responses.add(responses.GET, _LIST, body=_fx("helsingor_list.html"))
    responses.add(responses.GET, _detail("166122"), status=500)
    responses.add(responses.GET, _detail("166057"), body=_fx("helsingor_166057.html"))

    drain_errors()
    postings = signatur.scrape({"signatur_companies": ["2296"]})

    assert len(postings) == 2
    assert postings[0]["description"] == "" and postings[0]["title"]
    assert drain_errors()["signatur"]


def test_scrape_without_clients_is_empty():
    assert signatur.scrape({}) == []
    assert signatur.probe({}) is None


@responses.activate
def test_probe_reads_the_list_only():
    responses.add(responses.GET, _LIST, body=_fx("helsingor_list.html"))

    result = signatur.probe({"signatur_companies": ["2296"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 2
    assert len(responses.calls) == 1
