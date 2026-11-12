"""Fixture tests for the Ashby job-board API (issue #230): a real Pleo board,
trimmed to two jobs, plus an unlisted copy."""

import pytest
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.feeds import ashby
from paths import TESTS_DIR

_BOARD = "https://api.ashbyhq.com/posting-api/job-board/pleo"


def _fx() -> str:
    return (TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "ashby" / "pleo.json").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_maps_the_listed_jobs_and_skips_unlisted_ones():
    responses.add(responses.GET, _BOARD, body=_fx())

    postings = ashby.scrape({"ashby_companies": ["pleo"]})

    assert [p["platform_id"] for p in postings] == ["9c184331-fdba-487b-a227-0194345ef17f",
                                                    "1469f1e9-4aa2-4f48-af8b-490e074faf8e"]
    first = postings[0]
    JobPosting.model_validate(first)
    assert first["title"] == "Legal Counsel - Employment Law Leaning (Mat Cover)"
    assert first["company"] == "pleo"
    assert first["location"] == "Copenhagen"
    assert first["url"] == "https://jobs.ashbyhq.com/pleo/9c184331-fdba-487b-a227-0194345ef17f"
    assert first["apply_url"].endswith("/application") and first["apply_type"] == "external"
    assert first["posted_at"].startswith("2026-09-04")
    assert first["description"].startswith("ABOUT PLEO")
    assert first["source"] == "ashby"


@responses.activate
def test_an_unknown_board_is_a_recorded_error():
    responses.add(responses.GET, "https://api.ashbyhq.com/posting-api/job-board/nope", status=404, body="Not Found")
    responses.add(responses.GET, _BOARD, body=_fx())

    drain_errors()
    postings = ashby.scrape({"ashby_companies": ["nope", "pleo"]})

    assert len(postings) == 2
    assert "nope" in drain_errors()["ashby"][0]


@responses.activate
def test_a_board_listed_twice_is_read_once_per_job():
    responses.add(responses.GET, _BOARD, body=_fx())

    postings = ashby.scrape({"ashby_companies": ["pleo", "https://jobs.ashbyhq.com/pleo"]})

    assert len(postings) == 2


def test_no_companies_no_request():
    assert ashby.scrape({}) == []
    assert ashby.probe({}) is None


@responses.activate
def test_probe_reads_the_first_board():
    responses.add(responses.GET, _BOARD, body=_fx())

    result = ashby.probe({"ashby_companies": ["pleo", "lunar"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 2


@responses.activate
def test_probe_drift_without_a_jobs_list():
    responses.add(responses.GET, _BOARD, json={"apiVersion": "1"})

    assert ashby.probe({"ashby_companies": ["pleo"]})["structure_ok"] is False


@responses.activate
def test_the_followed_name_wins():
    responses.add(responses.GET, _BOARD, body=_fx())

    postings = ashby.scrape({"ashby_companies": ["https://jobs.ashbyhq.com/Pleo"],
                             "_names": {"ashby_companies": {"jobs.ashbyhq.com/pleo": "Pleo Technologies"}}})

    assert postings and {p["company"] for p in postings} == {"Pleo Technologies"}
    assert all(p["id"].startswith("ashby.") for p in postings)


@responses.activate
def test_without_a_name_map_the_board_is_the_fallback():
    responses.add(responses.GET, _BOARD, body=_fx())

    assert {p["company"] for p in ashby.scrape({"ashby_companies": ["pleo"]})} == {"pleo"}


@responses.activate
def test_scrape_drops_foreign_jobs_but_keeps_remote_and_multi_location_ones():
    import json
    from door.scrapers import drain_non_local
    data = json.loads(_fx())
    jobs = data["jobs"]
    jobs[0].update(location="London, UK", isRemote=False, workplaceType=None, secondaryLocations=[])
    jobs[1].update(location="London, UK", isRemote=False, workplaceType=None,
                   secondaryLocations=[{"location": "Budapest, Hungary"}])
    jobs.append({**jobs[1], "id": "remote-1", "jobUrl": "https://jobs.ashbyhq.com/pleo/remote1", "applyUrl": "u/application",
                 "location": "Europe", "secondaryLocations": [], "isRemote": True})
    responses.add(responses.GET, _BOARD, body=json.dumps(data))
    drain_non_local("ashby")

    postings = ashby.scrape({"ashby_companies": ["pleo"], "location": "Budapest, Hungary"})

    assert [p["location"] for p in postings] == ["London, UK; Budapest, Hungary", "Remote, Europe"]
    assert drain_non_local("ashby") == 1
