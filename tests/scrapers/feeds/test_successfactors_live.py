"""Live smoke test for the SuccessFactors scraper.

Calls the real Novo Nordisk SuccessFactors RMK career site
(careers.novonordisk.com) and verifies the contract: at least one valid
JobPosting with non-empty title, company, and url.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import successfactors


@pytest.mark.live
def test_successfactors_live_returns_valid_postings():
    postings = successfactors.scrape({"successfactors_companies": ["careers.novonordisk.com"]})
    assert len(postings) >= 1, "Expected at least one posting from live SuccessFactors feed"
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"], f"Missing title: {p}"
        assert p["company"], f"Missing company: {p}"
        assert p["url"], f"Missing url: {p}"
        assert p["source"] == "successfactors"
