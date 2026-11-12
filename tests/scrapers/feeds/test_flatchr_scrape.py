"""Fixture tests for the Flatchr feed: Flatchr's own career site, trimmed to three vacancies."""

import json

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local, drain_pushback
from door.scrapers.feeds import flatchr
from paths import TESTS_DIR

_FEED = "https://careers.flatchr.io/company/flatchr.json"
_DIR = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "flatchr"


def _fx(name="flatchr.json") -> str:
    return (_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_maps_every_vacancy():
    responses.add(responses.GET, _FEED, body=_fx())

    postings = flatchr.scrape({"flatchr_companies": ["flatchr"]})

    assert len(postings) == 3
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["description"] and p["source"] == "flatchr" and p["apply_type"] == "external"
    first = postings[0]
    assert first["title"] == "Account exective _HR Tech"
    assert first["company"] == "Flatchr"
    assert first["id"] == "flatchr.698941" and first["platform_id"] == "698941"
    assert first["location"] == "Boulogne-Billancourt, France"
    assert first["url"] == "https://careers.flatchr.io/fr/company/flatchr/vacancy/d86rjpggyaape17e-account-exective-_hr-tech"
    assert first["posted_at"].startswith("2026-10-09")
    assert "cycle de vente" in first["description"] and "<" not in first["description"]
    english = [p for p in postings if p["title"].startswith("🚀 Senior")]
    assert english and "small tech team" in english[0]["description"]  # an English ad comes through as is
    assert len([p for p in postings if "cycle de vente" in p["description"]]) == 1  # a French one too


@responses.activate
def test_one_request_per_company_and_no_paging():
    responses.add(responses.GET, _FEED, body=_fx())

    flatchr.scrape({"flatchr_companies": ["flatchr", "flatchr.flatchr.io"]})

    assert [c.request.url for c in responses.calls] == [_FEED]  # the same company twice is read once


@responses.activate
def test_known_ids_are_still_returned_without_extra_requests():
    responses.add(responses.GET, _FEED, body=_fx())

    postings = flatchr.scrape({"flatchr_companies": ["flatchr"]}, known_ids=frozenset({"698941"}))

    assert len(responses.calls) == 1 and len(postings) == 3  # the engine drops known ads; no detail fetch exists


@responses.activate
def test_an_unknown_company_is_a_recorded_error():
    responses.add(responses.GET, "https://careers.flatchr.io/company/nope.json", body=_fx("not_found.json"), status=404)
    responses.add(responses.GET, _FEED, body=_fx())

    drain_errors()
    assert len(flatchr.scrape({"flatchr_companies": ["nope", "flatchr"]})) == 3
    assert "nope" in drain_errors()["flatchr"][0]


@responses.activate
def test_a_page_that_is_not_a_job_list_is_a_recorded_error():
    responses.add(responses.GET, _FEED, json={"statusCode": 404, "error": "Not Found"})

    drain_errors()
    assert flatchr.scrape({"flatchr_companies": ["flatchr"]}) == []
    assert drain_errors()["flatchr"]


@responses.activate
@pytest.mark.parametrize("status", [403, 429])
def test_pushback_is_recorded(status):
    responses.add(responses.GET, _FEED, status=status)

    drain_errors(); drain_pushback("flatchr")
    assert flatchr.scrape({"flatchr_companies": ["flatchr"]}) == []
    assert drain_pushback("flatchr")
    assert drain_errors()["flatchr"]


def test_no_companies_no_request():
    assert flatchr.scrape({}) == []
    assert flatchr.probe({}) is None


@responses.activate
def test_the_followed_name_wins():
    responses.add(responses.GET, _FEED, body=_fx())

    postings = flatchr.scrape({"flatchr_companies": ["flatchr"], "_names": {"flatchr_companies": {"flatchr": "Flatchr SAS"}}})

    assert len(postings) == 3 and {p["company"] for p in postings} == {"Flatchr SAS"}


@responses.activate
def test_scrape_drops_postings_in_another_country_and_counts_them():
    data = json.loads(_fx())
    data["items"][0]["vacancy"]["address"] = {"locality": "Budapest", "country": "Hungary"}
    responses.add(responses.GET, _FEED, body=json.dumps(data))
    drain_non_local("flatchr")

    postings = flatchr.scrape({"flatchr_companies": ["flatchr"], "location": "Paris, France"})

    assert len(postings) == 2 and all("Budapest" not in p["location"] for p in postings)
    assert drain_non_local("flatchr") == 1


# --- probe ---

@responses.activate
def test_probe_reads_the_first_company_with_one_request():
    responses.add(responses.GET, _FEED, body=_fx())

    drain_errors()
    result = flatchr.probe({"flatchr_companies": ["flatchr", "other"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 3
    assert len(responses.calls) == 1 and not drain_errors()


@responses.activate
def test_probe_drift_without_the_item_list():
    data = json.loads(_fx())
    responses.add(responses.GET, _FEED, body=json.dumps({"results": data["items"]}))

    result = flatchr.probe({"flatchr_companies": ["flatchr"]})

    assert result["structure_ok"] is False and result["reason"]


@responses.activate
def test_probe_wall_and_unreachable():
    responses.add(responses.GET, _FEED, status=403)
    assert flatchr.probe({"flatchr_companies": ["flatchr"]}).get("wall")

    responses.replace(responses.GET, _FEED, body=requests.ConnectionError("down"))
    assert flatchr.probe({"flatchr_companies": ["flatchr"]}).get("unreachable")
