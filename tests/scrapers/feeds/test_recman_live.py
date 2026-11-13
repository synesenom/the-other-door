"""Live smoke test for Recman: Jobconnect Sweden's career site (a few open jobs, in Swedish).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import recman
from live_utils import assert_detects


@pytest.mark.live
def test_recman_live_returns_valid_postings():
    postings = recman.scrape({"recman_companies": ["jobconnectsverige"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]


@pytest.mark.live
def test_recman_detection_live():
    """A real employer's careers page still shows recman and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("recman")
