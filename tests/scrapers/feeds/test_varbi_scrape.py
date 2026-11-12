"""Fixture tests for Varbi (issue #525): Karolinska Institutet's and KTH's boards, trimmed and rewritten."""

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local
from door.scrapers.feeds import varbi
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "varbi"
_RSS = "https://ki.varbi.com/what:rssfeed/"
_LIST = "https://ki.varbi.com/"


def _read(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _serve_ki(rss: str | None = None):
    responses.add(responses.GET, _RSS, body=rss if rss is not None else _read("ki_rss.xml"),
                  content_type="application/rss+xml")
    responses.add(responses.GET, _LIST, body=_read("ki_list.html"))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_maps_every_ad_with_its_text_and_place():
    _serve_ki()

    postings = varbi.scrape({"varbi_tenants": ["ki"]})

    assert len(postings) == 3
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "varbi" and p["company"] == "Karolinska Institutet (KI)"
        assert p["description"] and "<" not in p["description"]
    english = postings[0]
    assert english["title"].startswith("Postdoctoral Research Associate")
    assert english["location"] == "Solna"
    assert english["posted_at"].startswith("2026-10-29T00:00:00")  # midnight, +01:00
    assert postings[1]["title"] == "Erfaren Systemutvecklare till forskningsinfrastruktur"
    assert postings[1]["description"].startswith("Bygg framtidens diagnostik")
    assert postings[1]["location"] == "Stockholm"
    assert [c.request.url for c in responses.calls] == [_RSS, _LIST]   # the ads' text is in the feed: no detail page


@responses.activate
def test_known_ads_cost_no_request_so_they_are_still_returned():
    _serve_ki()
    known = frozenset({"ki.varbi.com-985313"})

    assert len(varbi.scrape({"varbi_tenants": ["ki"]}, known)) == 3
    assert len(responses.calls) == 2


@responses.activate
def test_the_followed_name_wins():
    _serve_ki()

    postings = varbi.scrape({"varbi_tenants": ["ki"], "_names": {"varbi_tenants": {"ki": "Karolinska"}}})

    assert {p["company"] for p in postings} == {"Karolinska"}


@responses.activate
def test_two_tenants_are_two_boards_and_an_ad_listed_twice_counts_once():
    _serve_ki()
    responses.add(responses.GET, "https://kth.varbi.com/what:rssfeed/", body=_read("kth_rss.xml"))
    responses.add(responses.GET, "https://kth.varbi.com/", body=_read("kth_list.html"))

    postings = varbi.scrape({"varbi_tenants": ["ki", "kth", "ki"]})

    assert len(postings) == 5
    assert {p["company"] for p in postings} == {"Karolinska Institutet (KI)", "KTH Royal Institute of Technology"}
    assert len({p["id"] for p in postings}) == 5


@responses.activate
def test_a_failed_list_keeps_the_ads_without_a_place_and_records_it():
    responses.add(responses.GET, _RSS, body=_read("ki_rss.xml"))
    responses.add(responses.GET, _LIST, status=500)
    drain_errors()

    postings = varbi.scrape({"varbi_tenants": ["ki"]})

    assert len(postings) == 3 and {p["location"] for p in postings} == {""}
    assert any("ki" in e for e in drain_errors()["varbi"])


@responses.activate
def test_a_failed_feed_is_a_recorded_error_not_a_raise():
    responses.add(responses.GET, _RSS, status=500)
    drain_errors()

    assert varbi.scrape({"varbi_tenants": ["ki"]}) == []
    assert drain_errors()["varbi"]


@responses.activate
def test_a_refusal_is_a_recorded_error():
    responses.add(responses.GET, _RSS, status=403)
    drain_errors()

    assert varbi.scrape({"varbi_tenants": ["ki"]}) == []
    assert drain_errors()["varbi"]


@responses.activate
def test_an_unknown_tenant_is_a_recorded_error_and_the_rest_go_on():
    responses.add(responses.GET, "https://nope.varbi.com/what:rssfeed/", status=404, body="Error 404, Page not found.")
    _serve_ki()
    drain_errors()

    assert len(varbi.scrape({"varbi_tenants": ["nope", "ki"]})) == 3
    assert "nope" in drain_errors()["varbi"][0]


@responses.activate
def test_a_page_that_is_not_a_feed_is_a_recorded_error():
    _serve_ki("<html><body>Maintenance</body></html>")
    drain_errors()

    assert varbi.scrape({"varbi_tenants": ["ki"]}) == []
    assert drain_errors()["varbi"]


@responses.activate
def test_scrape_drops_ads_in_another_country():
    _serve_ki()
    responses.replace(responses.GET, _LIST, body=_read("ki_list.html").replace("Solna", "Vienna, Austria"))
    drain_non_local("varbi")

    postings = varbi.scrape({"varbi_tenants": ["ki"], "location": "Stockholm, Sweden"})

    assert len(postings) == 2
    assert drain_non_local("varbi") == 1


def test_no_tenants_no_request():
    assert varbi.scrape({}) == []
    assert varbi.probe({}) is None


@responses.activate
def test_probe_reads_the_first_tenants_feed_with_one_request():
    responses.add(responses.GET, _RSS, body=_read("ki_rss.xml"))
    drain_errors()

    result = varbi.probe({"varbi_tenants": ["ki", "kth"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 3
    assert len(responses.calls) == 1
    assert drain_errors() == {}


@responses.activate
def test_probe_drift_without_a_feed():
    responses.add(responses.GET, _RSS, body=_read("ki_rss.xml").replace("<channel>", "<chan>").replace("</channel>", "</chan>"))

    result = varbi.probe({"varbi_tenants": ["ki"]})

    assert result["structure_ok"] is False and result["reason"]


@responses.activate
def test_probe_unreachable_and_wall():
    responses.add(responses.GET, _RSS, body=requests.ConnectionError("down"))
    down = varbi.probe({"varbi_tenants": ["ki"]})
    assert down["structure_ok"] is False and down.get("unreachable") is True
    responses.replace(responses.GET, _RSS, status=403)
    walled = varbi.probe({"varbi_tenants": ["ki"]})
    assert walled["structure_ok"] is False and walled.get("wall") is True
