"""Live smoke test for the Greenhouse scraper.

Calls the real Greenhouse boards API for the public Greenhouse board token
("greenhouse") and verifies the contract: at least one valid JobPosting with
non-empty title, company, and url.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import greenhouse
from live_utils import assert_detects


@pytest.mark.live
def test_greenhouse_live_returns_valid_postings():
    postings = greenhouse.scrape({"greenhouse_boards": ["greenhouse"]})
    assert len(postings) >= 1, "Expected at least one posting from live Greenhouse board"
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"], f"Missing title: {p}"
        assert p["company"], f"Missing company: {p}"
        assert p["url"], f"Missing url: {p}"
        assert p["source"] == "greenhouse"


@pytest.mark.live
def test_greenhouse_live_reads_a_danish_company():
    """Trustpilot, a Danish company."""
    postings = greenhouse.scrape({"greenhouse_boards": ["trustpilot"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"]


@pytest.mark.live
def test_greenhouse_detection_live():
    """A real employer's careers page still shows greenhouse and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("greenhouse")
