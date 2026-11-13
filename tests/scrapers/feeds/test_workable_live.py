"""Live smoke test for the Workable job-search scraper (jobs.workable.com).

Searches a broad keyword in a large city, one page only, and checks the contract:
at least one valid JobPosting with non-empty title, company and url.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import workable
from live_utils import NONSENSE_KEYWORD as KW, assert_field_contract, assert_zero_hits, drain_zero_hit_state


@pytest.mark.live
def test_live_workable_returns_postings():
    config = {"search_keywords": ["engineer"], "location": "London", "max_pages_per_keyword": 1}
    postings = workable.scrape(config)
    assert len(postings) >= 1, "Expected at least one posting from Workable's job search"
    assert_field_contract("workable", postings, config, mode="search")
    assert all(p["source"] == "workable" for p in postings)


@pytest.mark.live
def test_workable_live_reads_a_danish_company():
    """Dreamdata, through the jobs widget (issue #227)."""
    postings = workable.scrape({"workable_companies": ["dreamdata"]})
    assert postings
    assert_field_contract("workable", postings, mode="collect")


@pytest.mark.live
def test_workable_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("workable")
    postings = workable.scrape({"search_keywords": [KW], "location": "London", "max_pages_per_keyword": 1, "_mode": "search"})
    assert_zero_hits("workable", postings)
