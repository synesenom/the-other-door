"""Unit tests for the Ashby job-board API's pure helpers (issue #230)."""

import pytest

from door.scrapers.feeds import ashby


@pytest.mark.parametrize("entry, slug", [
    ("pleo", "pleo"),
    (" Pleo ", "pleo"),
    ("https://jobs.ashbyhq.com/pleo", "pleo"),
    ("jobs.ashbyhq.com/lunar/1469f1e9-4aa2", "lunar"),
])
def test_board_name_accepts_a_slug_or_a_board_url(entry, slug):
    assert ashby._board_name(entry) == slug


def test_location_text_joins_secondary_locations_and_marks_remote_work():
    job = {"location": "Copenhagen", "secondaryLocations": [{"location": "Lisbon"}, {"location": "London"}]}
    assert ashby._location_text(job) == "Copenhagen; Lisbon; London"
    assert ashby._location_text({"location": "Denmark", "workplaceType": "Remote"}) == "Remote, Denmark"
    assert ashby._location_text({"location": "Copenhagen", "isRemote": True, "workplaceType": "Hybrid"}) == "Copenhagen"
    assert ashby._location_text({"location": "", "isRemote": True}) == "Remote"

# --- feed detection (issue #282) ---

def _d(det):
    return None if det is None else (det.platform, det.entry)


def test_detect_url():
    assert _d(ashby.detect_url("https://jobs.ashbyhq.com/pleo/9c184331")) == ("ashby", "pleo")
    assert ashby.detect_url("https://jobs.ashbyhq.com/") is None
    assert ashby.detect_url("https://www.ashbyhq.com/pleo") is None


def test_an_ashby_name_probe_is_the_job_board_api():
    (probe,) = ashby.name_probes("acme")
    assert (probe.url, probe.key) == ("https://api.ashbyhq.com/posting-api/job-board/acme", "jobs")
    assert ashby.feed_url("acme") is None
