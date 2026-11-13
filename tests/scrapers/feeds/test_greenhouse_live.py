"""Live smoke test for the Greenhouse scraper.

Calls the real Greenhouse boards API for the public Greenhouse board token
("greenhouse") and verifies the contract: at least one valid JobPosting with
non-empty title, company, and url.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import greenhouse
from live_utils import assert_field_contract


@pytest.mark.live
def test_greenhouse_live_returns_valid_postings():
    postings = greenhouse.scrape({"greenhouse_boards": ["greenhouse"]})
    assert len(postings) >= 1, "Expected at least one posting from live Greenhouse board"
    assert_field_contract("greenhouse", postings, mode="collect")
    assert all(p["source"] == "greenhouse" for p in postings)


@pytest.mark.live
def test_greenhouse_live_reads_a_danish_company():
    """Trustpilot, a Danish company."""
    postings = greenhouse.scrape({"greenhouse_boards": ["trustpilot"]})
    assert postings
    assert_field_contract("greenhouse", postings, mode="collect")
