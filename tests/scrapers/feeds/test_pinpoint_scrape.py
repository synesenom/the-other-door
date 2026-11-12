"""Fixture tests for the Pinpoint postings feed: Factbird's live postings, trimmed."""

import pytest
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.feeds import pinpoint
from paths import TESTS_DIR

_FEED = "https://factbird.pinpointhq.com/postings.json"


def _fx() -> str:
    return (TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "pinpoint" / "factbird.json").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_maps_every_posting():
    responses.add(responses.GET, _FEED, body=_fx())

    postings = pinpoint.scrape({"pinpoint_companies": ["factbird"]})

    assert len(postings) == 2
    first = postings[0]
    JobPosting.model_validate(first)
    assert first["title"] == "Full Stack Cloud Engineer"
    assert first["company"] == "Factbird"
    assert first["platform_id"] == "factbird.pinpointhq.com-558575"
    assert first["id"] == "pinpoint.factbird-pinpointhq-com-558575"
    assert first["location"] == "Copenhagen"
    assert first["url"] == "https://factbird.pinpointhq.com/en/postings/996b5103-670d-47bd-b596-c4f7be99b116"
    assert first["apply_type"] == "external"
    assert first["description"].startswith("Factbird helps manufacturers")
    assert "Flexible working hours" in first["description"]  # benefits included
    assert "<" not in first["description"]
    assert first["source"] == "pinpoint"
    assert postings[1]["location"] == "Remote, United States"


@responses.activate
def test_an_unknown_company_is_a_recorded_error():
    responses.add(responses.GET, "https://nope.pinpointhq.com/postings.json", status=404)
    responses.add(responses.GET, _FEED, body=_fx())

    drain_errors()
    assert len(pinpoint.scrape({"pinpoint_companies": ["nope", "factbird"]})) == 2
    assert "nope" in drain_errors()["pinpoint"][0]


def test_no_companies_no_request():
    assert pinpoint.scrape({}) == []
    assert pinpoint.probe({}) is None


@responses.activate
def test_probe_reads_the_first_company():
    responses.add(responses.GET, _FEED, body=_fx())

    result = pinpoint.probe({"pinpoint_companies": ["factbird", "other"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 2


@responses.activate
def test_probe_drift_without_a_data_list():
    responses.add(responses.GET, _FEED, json={"jobs": []})

    assert pinpoint.probe({"pinpoint_companies": ["factbird"]})["structure_ok"] is False


@responses.activate
def test_the_followed_name_wins():
    responses.add(responses.GET, _FEED, body=_fx())

    postings = pinpoint.scrape({"pinpoint_companies": ["factbird"], "_names": {"pinpoint_companies": {"factbird": "Factbird ApS"}}})

    assert len(postings) == 2 and {p["company"] for p in postings} == {"Factbird ApS"}
    assert all(p["id"].startswith("pinpoint.") for p in postings)


@responses.activate
def test_without_a_name_map_the_guessed_name_is_the_fallback():
    responses.add(responses.GET, _FEED, body=_fx())

    assert {p["company"] for p in pinpoint.scrape({"pinpoint_companies": ["factbird"]})} == {"Factbird"}


@responses.activate
def test_scrape_drops_postings_in_another_country_and_counts_them():
    import json
    from door.scrapers import drain_non_local
    data = json.loads(_fx())
    data["data"][0]["location"] = {"city": "London", "name": "London, UK"}
    data["data"][1]["location"] = {"city": "Budapest", "name": "Budapest, Hungary"}
    data["data"][1]["workplace_type"] = "onsite"
    responses.add(responses.GET, _FEED, body=json.dumps(data))
    drain_non_local("pinpoint")

    postings = pinpoint.scrape({"pinpoint_companies": ["factbird"], "location": "Budapest, Hungary"})

    assert [p["location"] for p in postings] == ["Budapest, Hungary"]
    assert drain_non_local("pinpoint") == 1
