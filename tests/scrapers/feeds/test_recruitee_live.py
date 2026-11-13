"""Live smoke test for the Recruitee careers API: Famly (issue #231).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import recruitee
from live_utils import assert_detects


@pytest.mark.live
def test_recruitee_live_returns_valid_postings():
    postings = recruitee.scrape({"recruitee_companies": ["famly"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]


@pytest.mark.live
def test_recruitee_detection_live():
    """A real employer's careers page still shows recruitee and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("recruitee")
