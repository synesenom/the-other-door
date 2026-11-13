"""Live smoke test for the Dayforce candidate portal: Natus Sensory.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import dayforce
from live_utils import assert_detects


@pytest.mark.live
def test_dayforce_live_returns_valid_postings():
    postings = dayforce.scrape({"dayforce_companies": ["natus/CANDIDATEPORTALSENSORY"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]


@pytest.mark.live
def test_dayforce_detection_live():
    """A real employer's careers page still shows dayforce and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("dayforce")
