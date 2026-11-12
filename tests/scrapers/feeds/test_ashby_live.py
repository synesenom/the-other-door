"""Live smoke test for the Ashby job-board API: Pleo (issue #230).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import ashby


@pytest.mark.live
def test_ashby_live_returns_valid_postings():
    postings = ashby.scrape({"ashby_companies": ["pleo"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
