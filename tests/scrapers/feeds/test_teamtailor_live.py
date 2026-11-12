"""Live smoke test for the TeamTailor scraper.

Calls the real TeamTailor public jobs feed for a confirmed-good company board
("storytel") and verifies the contract: at least one valid JobPosting with
non-empty title, company, and url.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import teamtailor


@pytest.mark.live
def test_teamtailor_live_returns_valid_postings():
    postings = teamtailor.scrape({"teamtailor_companies": ["storytel"]})
    assert len(postings) >= 1, "Expected at least one posting from live TeamTailor board"
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"], f"Missing title: {p}"
        assert p["company"], f"Missing company: {p}"
        assert p["url"], f"Missing url: {p}"
        assert p["source"] == "teamtailor"


@pytest.mark.live
def test_teamtailor_live_reads_a_danish_company():
    """Templafy, a Danish company."""
    postings = teamtailor.scrape({"teamtailor_companies": ["templafy"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"]
