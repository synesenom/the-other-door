"""Fixture tests for the Dayforce candidate portal: Natus Sensory's live postings, trimmed and their ad text rewritten."""

import json

import pytest
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.feeds import dayforce
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "dayforce"
_CSRF = "https://jobs.dayforcehcm.com/api/auth/csrf"
_SEARCH = "https://jobs.dayforcehcm.com/api/geo/natus/jobposting/search"
_CONFIG = {"dayforce_companies": ["natus/CANDIDATEPORTALSENSORY"]}


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _mock():
    responses.add(responses.GET, _CSRF, body=_fx("csrf.json"))
    responses.add(responses.POST, _SEARCH, body=_fx("natus_page1.json"))
    responses.add(responses.POST, _SEARCH, body=_fx("natus_page2.json"))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_pages_the_search_and_maps_every_posting():
    _mock()

    postings = dayforce.scrape(_CONFIG)

    assert [p["platform_id"] for p in postings] == ["natus-3518", "natus-3288", "natus-3555"]
    second = postings[1]
    JobPosting.model_validate(second)
    assert second["title"] == "Project Manager (remote in Europe)"
    assert second["company"] == "Natus"
    assert second["location"].startswith("Denmark - Remote (Sensory)")
    assert second["url"] == "https://jobs.dayforcehcm.com/en-US/natus/CANDIDATEPORTALSENSORY/jobs/3288"
    assert second["apply_url"] == second["url"]
    assert second["posted_at"].startswith("2026-09-09T04:00:00")
    assert second["description"].startswith("Location: Remote somewhere in Europe")
    assert "&nbsp;" not in postings[0]["description"]
    assert second["source"] == "dayforce"


@responses.activate
def test_the_csrf_token_and_page_offset_are_sent():
    _mock()

    dayforce.scrape(_CONFIG)

    first, second = [c.request for c in responses.calls if c.request.method == "POST"]
    assert first.headers["X-CSRF-TOKEN"].startswith("3790550f")
    assert json.loads(first.body) == {"clientNamespace": "natus", "jobBoardCode": "CANDIDATEPORTALSENSORY",
                                      "cultureCode": "en-US", "distanceUnit": 0, "paginationStart": 0}
    assert json.loads(second.body)["paginationStart"] == 2


@responses.activate
def test_known_ids_are_left_out():
    _mock()

    postings = dayforce.scrape(_CONFIG, known_ids=frozenset({"natus-3518", "natus-3555"}))

    assert [p["platform_id"] for p in postings] == ["natus-3288"]


@responses.activate
def test_a_failing_portal_is_a_recorded_error():
    responses.add(responses.GET, _CSRF, status=500)

    drain_errors()
    assert dayforce.scrape(_CONFIG) == []
    assert "natus/CANDIDATEPORTALSENSORY" in drain_errors()["dayforce"][0]


@responses.activate
def test_a_rejected_search_is_a_recorded_error():
    responses.add(responses.GET, _CSRF, body=_fx("csrf.json"))
    responses.add(responses.POST, _SEARCH, status=403)

    drain_errors()
    assert dayforce.scrape(_CONFIG) == []
    assert drain_errors()["dayforce"]


def test_scrape_without_portals_is_empty():
    assert dayforce.scrape({}) == []
    assert dayforce.probe({}) is None


@responses.activate
def test_probe_reads_the_first_page_only():
    responses.add(responses.GET, _CSRF, body=_fx("csrf.json"))
    responses.add(responses.POST, _SEARCH, body=_fx("natus_page1.json"))

    result = dayforce.probe(_CONFIG)

    assert result["structure_ok"] is True and len(result["postings"]) == 2


@responses.activate
def test_the_followed_name_wins():
    _mock()

    postings = dayforce.scrape({**_CONFIG, "_names": {"dayforce_companies": {"natus/candidateportalsensory": "Natus Medical"}}})

    assert len(postings) == 3 and {p["company"] for p in postings} == {"Natus Medical"}
    assert all(p["id"].startswith("dayforce.") for p in postings)


@responses.activate
def test_without_a_name_map_the_client_is_the_fallback():
    _mock()

    assert {p["company"] for p in dayforce.scrape(_CONFIG)} == {"Natus"}


@responses.activate
def test_scrape_drops_postings_in_another_country_but_keeps_virtual_ones():
    from door.scrapers import drain_non_local
    page1 = json.loads(_fx("natus_page1.json"))
    page1["jobPostings"][0]["postingLocations"][0]["formattedAddress"] = "London, UK"
    page1["jobPostings"][1]["postingLocations"][0]["formattedAddress"] = "Europe"
    page1["jobPostings"][1]["hasVirtualLocation"] = True
    responses.add(responses.GET, _CSRF, body=_fx("csrf.json"))
    responses.add(responses.POST, _SEARCH, body=json.dumps(page1))
    responses.add(responses.POST, _SEARCH, body=_fx("natus_page2.json"))
    drain_non_local("dayforce")

    postings = dayforce.scrape({**_CONFIG, "location": "Budapest, Hungary"})

    assert "natus-3518" not in [p["platform_id"] for p in postings]
    assert [p["platform_id"] for p in postings] == ["natus-3288"]
    assert drain_non_local("dayforce") == 2  # London, and page 2's Bengaluru
