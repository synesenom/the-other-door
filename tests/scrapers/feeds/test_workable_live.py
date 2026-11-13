"""Live smoke test for the Workable job-search scraper (jobs.workable.com).

Searches a broad keyword in a large city, one page only, and checks the contract:
at least one valid JobPosting with non-empty title, company and url.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import workable
from live_utils import NONSENSE_KEYWORD as KW, assert_zero_hits, drain_zero_hit_state


@pytest.mark.live
def test_live_workable_returns_postings():
    postings = workable.scrape(
        {"search_keywords": ["engineer"], "location": "London", "max_pages_per_keyword": 1})
    assert len(postings) >= 1, "Expected at least one posting from Workable's job search"
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"], "title must not be empty"
        assert p["company"], "company must not be empty"
        assert p["url"], "url must not be empty"
        assert p["source"] == "workable"


@pytest.mark.live
def test_workable_live_reads_a_danish_company():
    """Dreamdata, through the jobs widget (issue #227)."""
    postings = workable.scrape({"workable_companies": ["dreamdata"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"]


@pytest.mark.live
def test_workable_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("workable")
    postings = workable.scrape({"search_keywords": [KW], "location": "London", "max_pages_per_keyword": 1, "_mode": "search"})
    assert_zero_hits("workable", postings)
