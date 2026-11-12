"""Live smoke test for the Lever scraper.

Calls the real Lever API for Kavak's public Lever board and verifies
the contract: at least one valid JobPosting with non-empty title, company,
and url.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import lever


@pytest.mark.live
def test_lever_live_returns_valid_postings():
    postings = lever.scrape({"lever_companies": ["kavak"]})
    assert len(postings) >= 1, "Expected at least one posting from Kavak's Lever board"
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"], f"Missing title: {p}"
        assert p["company"], f"Missing company: {p}"
        assert p["url"], f"Missing url: {p}"
        assert p["source"] == "lever"


@pytest.mark.live
def test_lever_live_reads_a_danish_company():
    """Siteimprove, on the EU host (issue #227)."""
    postings = lever.scrape({"lever_companies": ["siteimprove"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"]
