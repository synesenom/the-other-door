"""Live smoke test for the Lever scraper.

Calls the real Lever API for Kavak's public Lever board and verifies
the contract: at least one valid JobPosting with non-empty title, company,
and url.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import lever
from live_utils import assert_detects, assert_field_contract


@pytest.mark.live
def test_lever_live_returns_valid_postings():
    postings = lever.scrape({"lever_companies": ["kavak"]})
    assert len(postings) >= 1, "Expected at least one posting from Kavak's Lever board"
    assert_field_contract("lever", postings, mode="collect")
    assert all(p["source"] == "lever" for p in postings)


@pytest.mark.live
def test_lever_live_reads_a_danish_company():
    """Siteimprove, on the EU host (issue #227)."""
    postings = lever.scrape({"lever_companies": ["siteimprove"]})
    assert postings
    assert_field_contract("lever", postings, mode="collect")


@pytest.mark.live
def test_lever_detection_live():
    """A real employer's careers page still shows lever and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("lever")
