"""Fixture tests for Eploy (issue #603): the public RSS data feed of Vitality (an ``eploy.net`` host) and of the Alan
Turing Institute (a custom domain), trimmed and rewritten."""

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local
from door.scrapers.feeds import eploy
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "eploy"
_VITALITY = "https://vitalityweb.eploy.net/feeds/datafeed.ashx"
_TURING = "https://portal.careers.turing.ac.uk/feeds/datafeed.ashx"


def _read(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _serve(url=_VITALITY, name="vitality_feed.xml", body=None):
    responses.add(responses.GET, url, body=body or _read(name), content_type="text/xml")   # no charset: still UTF-8


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_maps_every_ad_with_its_whole_text():
    _serve()

    postings = eploy.scrape({"eploy_hosts": ["vitalityweb.eploy.net"]})

    assert len(postings) == 3
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "eploy" and p["company"] == "Vitality"
        assert p["description"] and "<" not in p["description"]
    first = postings[0]
    assert first["title"] == "Head of Events and Experiences"
    assert first["location"] == "London"
    assert first["url"] == "https://vitalityweb.eploy.net/vacancies/21883/head-of-events-and-experiences.html"
    assert first["posted_at"].startswith("2026-11-03T00:00:00")
    assert first["id"] == "eploy.vitalityweb-eploy-net-21883"
    assert "A record of running a large events programme" in first["description"]
    assert [c.request.url for c in responses.calls] == [_VITALITY]   # the feed holds the text: no list, no ad page


@responses.activate
def test_known_ads_cost_no_request_so_they_are_still_returned():
    _serve()

    assert len(eploy.scrape({"eploy_hosts": ["vitalityweb.eploy.net"]}, frozenset({"21883"}))) == 3
    assert len(responses.calls) == 1


@responses.activate
def test_the_followed_name_wins_and_a_link_is_a_host():
    _serve()
    names = {"eploy_hosts": {"vitalityweb.eploy.net/vacancies": "Vitality Health"}}   # keyed by the entry as written

    postings = eploy.scrape({"eploy_hosts": ["https://vitalityweb.eploy.net/vacancies/"], "_names": names})

    assert {p["company"] for p in postings} == {"Vitality Health"}


@responses.activate
def test_a_custom_domain_is_its_own_host_and_two_hosts_are_two_feeds():
    _serve()
    _serve(_TURING, "turing_feed.xml")

    postings = eploy.scrape({"eploy_hosts": ["vitalityweb.eploy.net", "portal.careers.turing.ac.uk", "vitalityweb.eploy.net"]})

    assert len(postings) == 4
    assert {p["company"] for p in postings} == {"Vitality", "The Alan Turing Institute"}
    assert len({p["id"] for p in postings}) == 4


@responses.activate
def test_scrape_drops_ads_in_another_country_and_counts_them():
    _serve()
    drain_non_local("eploy")

    postings = eploy.scrape({"eploy_hosts": ["vitalityweb.eploy.net"], "location": "London, United Kingdom"})

    assert [p["title"] for p in postings] == ["Head of Events and Experiences", "Information Security Analyst"]
    assert drain_non_local("eploy") == 1


@responses.activate
def test_a_failed_feed_is_a_recorded_error_not_a_raise():
    responses.add(responses.GET, _VITALITY, status=500)
    drain_errors()

    assert eploy.scrape({"eploy_hosts": ["vitalityweb.eploy.net"]}) == []
    assert drain_errors()["eploy"]


@responses.activate
def test_a_refusal_is_a_recorded_error():
    responses.add(responses.GET, _VITALITY, status=403)
    drain_errors()

    assert eploy.scrape({"eploy_hosts": ["vitalityweb.eploy.net"]}) == []
    assert drain_errors()["eploy"]


@responses.activate
def test_an_unknown_host_is_a_recorded_error_and_the_rest_go_on():
    responses.add(responses.GET, "https://nope.eploy.net/feeds/datafeed.ashx", status=404, body="Not Found")
    _serve()
    drain_errors()

    assert len(eploy.scrape({"eploy_hosts": ["nope.eploy.net", "vitalityweb.eploy.net"]})) == 3
    assert "nope.eploy.net" in drain_errors()["eploy"][0]


@responses.activate
def test_a_page_that_is_not_a_feed_is_a_recorded_error():
    _serve(body="<html><body>Maintenance</body></html>")
    drain_errors()

    assert eploy.scrape({"eploy_hosts": ["vitalityweb.eploy.net"]}) == []
    assert drain_errors()["eploy"]


def test_no_hosts_no_request():
    assert eploy.scrape({}) == []
    assert eploy.probe({}) is None


@responses.activate
def test_probe_reads_a_few_ads_of_the_first_host_with_one_request():
    _serve(_VITALITY + "?RecordLimit=5")
    drain_errors()

    result = eploy.probe({"eploy_hosts": ["vitalityweb.eploy.net", "portal.careers.turing.ac.uk"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 3
    assert len(responses.calls) == 1
    assert "RecordLimit=5" in responses.calls[0].request.url
    assert drain_errors() == {}


@responses.activate
def test_probe_drift_without_a_feed():
    drifted = _read("vitality_feed.xml").replace("<channel>", "<chan>").replace("</channel>", "</chan>")
    _serve(_VITALITY + "?RecordLimit=5", body=drifted)

    result = eploy.probe({"eploy_hosts": ["vitalityweb.eploy.net"]})

    assert result["structure_ok"] is False and result["reason"]


@responses.activate
def test_probe_unreachable_and_wall():
    url = _VITALITY + "?RecordLimit=5"
    responses.add(responses.GET, url, body=requests.ConnectionError("down"))
    down = eploy.probe({"eploy_hosts": ["vitalityweb.eploy.net"]})
    assert down["structure_ok"] is False and down.get("unreachable") is True
    responses.replace(responses.GET, url, status=403)
    walled = eploy.probe({"eploy_hosts": ["vitalityweb.eploy.net"]})
    assert walled["structure_ok"] is False and walled.get("wall") is True
