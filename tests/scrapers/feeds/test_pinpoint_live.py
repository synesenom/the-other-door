"""Live smoke test for Pinpoint's public career-site feed: Factbird.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import pinpoint
from live_utils import assert_detects


@pytest.mark.live
def test_pinpoint_live_returns_valid_postings():
    postings = pinpoint.scrape({"pinpoint_companies": ["factbird"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]


@pytest.mark.live
def test_pinpoint_detection_live():
    """A real employer's careers page still shows pinpoint and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("pinpoint")
