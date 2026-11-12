"""Fixture tests for Personio (issue #558): PNO Group Europe's feed, trimmed and rewritten."""

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local
from door.scrapers.feeds import personio
from paths import TESTS_DIR

_XML = "https://pno-group-europe.jobs.personio.com/xml"


def _read() -> str:
    return (TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "personio" / "pno-group-europe.xml").read_text(
        encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_maps_every_position_in_any_language():
    responses.add(responses.GET, _XML, body=_read(), content_type="application/xml")

    postings = personio.scrape({"personio_companies": ["pno-group-europe"]})

    assert len(postings) == 5
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
    english = next(p for p in postings if p["platform_id"] == "2803716")
    assert english["description"].startswith("We need an administrative assistant")
    assert english["location"] == "Paris, France"
    assert english["posted_at"].startswith("2026-09-18")
    assert english["source"] == "personio"
    dutch = next(p for p in postings if p["platform_id"] == "2185891")
    assert dutch["title"] == "Fiscaal Adviseur" and "adviseert klanten" in dutch["description"]
    german = next(p for p in postings if p["platform_id"] == "1401049")
    assert "Werkstudent" in german["title"] and "Förderanträgen" in german["description"]


@responses.activate
def test_known_ads_cost_no_request_so_they_are_still_returned():
    responses.add(responses.GET, _XML, body=_read())

    postings = personio.scrape({"personio_companies": ["pno-group-europe"]}, known_ids=frozenset({"2803716"}))

    assert len(responses.calls) == 1 and len(postings) == 5


@responses.activate
def test_the_followed_name_wins():
    responses.add(responses.GET, _XML, body=_read())
    config = {"personio_companies": ["pno-group-europe"], "_names": {"personio_companies": {"pno-group-europe": "PNO Group"}}}

    assert {p["company"] for p in personio.scrape(config)} == {"PNO Group"}


@responses.activate
def test_a_position_listed_twice_counts_once():
    responses.add(responses.GET, _XML, body=_read())
    responses.add(responses.GET, "https://other.jobs.personio.com/xml", body=_read())

    assert len(personio.scrape({"personio_companies": ["pno-group-europe", "other"]})) == 5


@responses.activate
def test_a_de_account_is_read_on_its_own_host():
    responses.add(responses.GET, "https://acme.jobs.personio.de/xml", body=_read())

    assert len(personio.scrape({"personio_companies": ["acme.jobs.personio.de"]})) == 5


@responses.activate
def test_scrape_drops_positions_in_another_country():
    responses.add(responses.GET, _XML, body=_read())
    drain_non_local("personio")

    postings = personio.scrape({"personio_companies": ["pno-group-europe"], "location": "Paris, France"})

    assert {p["platform_id"] for p in postings} == {"2803716", "2461874"}  # (the UK ad is remote, but tied to the UK)
    assert drain_non_local("personio") == 3


@responses.activate
def test_a_failed_feed_is_a_recorded_error_not_a_raise():
    responses.add(responses.GET, _XML, status=500)
    drain_errors()

    assert personio.scrape({"personio_companies": ["pno-group-europe"]}) == []
    assert drain_errors()["personio"]


@responses.activate
def test_pushback_is_recorded():
    from door.scrapers import drain_pushback

    responses.add(responses.GET, _XML, status=429)
    drain_errors()
    drain_pushback("personio")

    assert personio.scrape({"personio_companies": ["pno-group-europe"]}) == []
    assert drain_pushback("personio")


@responses.activate
def test_an_unknown_account_is_a_recorded_error_and_the_rest_go_on():
    responses.add(responses.GET, "https://nope.jobs.personio.com/xml", status=404, body="<html>Page Not Found</html>")
    responses.add(responses.GET, _XML, body=_read())
    drain_errors()

    assert len(personio.scrape({"personio_companies": ["nope", "pno-group-europe"]})) == 5
    assert "nope" in drain_errors()["personio"][0]


@responses.activate
def test_a_page_that_is_not_a_feed_is_a_recorded_error():
    responses.add(responses.GET, _XML, body="<html><body>Maintenance</body></html>")
    drain_errors()

    assert personio.scrape({"personio_companies": ["pno-group-europe"]}) == []
    assert drain_errors()["personio"]


def test_no_accounts_no_request():
    assert personio.scrape({}) == []
    assert personio.probe({}) is None


@responses.activate
def test_probe_reads_the_first_account_with_one_request():
    responses.add(responses.GET, _XML, body=_read())
    drain_errors()

    result = personio.probe({"personio_companies": ["pno-group-europe", "other"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 5
    assert len(responses.calls) == 1
    assert drain_errors() == {}


@responses.activate
def test_probe_drift_without_the_positions_block():
    responses.add(responses.GET, _XML, body=_read().replace("workzag-jobs", "jobs"))

    result = personio.probe({"personio_companies": ["pno-group-europe"]})

    assert result["structure_ok"] is False and result["reason"]


@responses.activate
def test_probe_unreachable_and_wall():
    responses.add(responses.GET, _XML, body=requests.ConnectionError("down"))
    down = personio.probe({"personio_companies": ["pno-group-europe"]})
    assert down["structure_ok"] is False and down.get("unreachable") is True
    responses.replace(responses.GET, _XML, status=403)
    walled = personio.probe({"personio_companies": ["pno-group-europe"]})
    assert walled["structure_ok"] is False and walled.get("wall") is True
