"""Live smoke test for the SuccessFactors scraper.

Calls the real Novo Nordisk SuccessFactors RMK career site
(careers.novonordisk.com) and verifies the contract: at least one valid
JobPosting with non-empty title, company, and url.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import successfactors
from live_utils import assert_detects, assert_field_contract


@pytest.mark.live
def test_successfactors_live_returns_valid_postings():
    postings = successfactors.scrape({"successfactors_companies": ["careers.novonordisk.com"]})
    assert len(postings) >= 1, "Expected at least one posting from live SuccessFactors feed"
    assert_field_contract("successfactors", postings, mode="collect")
    assert all(p["source"] == "successfactors" for p in postings)


@pytest.mark.live
def test_successfactors_detection_live():
    """A real employer's careers page still shows successfactors and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("successfactors")
