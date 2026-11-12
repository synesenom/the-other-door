"""Live smoke test for Flatchr's public career-site feed: Flatchr's own careers page.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import flatchr


@pytest.mark.live
def test_flatchr_live_returns_valid_postings():
    postings = flatchr.scrape({"flatchr_companies": ["flatchr"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
