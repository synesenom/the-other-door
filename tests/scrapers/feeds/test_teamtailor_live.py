"""Live smoke test for the TeamTailor scraper.

Calls the real TeamTailor public jobs feed for a confirmed-good company board
("storytel") and verifies the contract: at least one valid JobPosting with
non-empty title, company, and url.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import teamtailor
from live_utils import assert_field_contract


@pytest.mark.live
def test_teamtailor_live_returns_valid_postings():
    postings = teamtailor.scrape({"teamtailor_companies": ["storytel"]})
    assert len(postings) >= 1, "Expected at least one posting from live TeamTailor board"
    assert_field_contract("teamtailor", postings, mode="collect")
    assert all(p["source"] == "teamtailor" for p in postings)


@pytest.mark.live
def test_teamtailor_live_reads_a_danish_company():
    """Templafy, a Danish company."""
    postings = teamtailor.scrape({"teamtailor_companies": ["templafy"]})
    assert postings
    assert_field_contract("teamtailor", postings, mode="collect")
