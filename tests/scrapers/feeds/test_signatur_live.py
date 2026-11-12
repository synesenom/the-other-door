"""Live smoke test for the Signatur job portal: Helsingør Kommune.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import signatur


@pytest.mark.live
def test_signatur_live_returns_valid_postings():
    postings = signatur.scrape({"signatur_companies": ["2296"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
