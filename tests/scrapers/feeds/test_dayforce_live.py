"""Live smoke test for the Dayforce candidate portal: Natus Sensory.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import dayforce
from live_utils import assert_detects, assert_field_contract


@pytest.mark.live
def test_dayforce_live_returns_valid_postings():
    postings = dayforce.scrape({"dayforce_companies": ["natus/CANDIDATEPORTALSENSORY"]})
    assert postings
    assert_field_contract("dayforce", postings, mode="collect")


@pytest.mark.live
def test_dayforce_detection_live():
    """A real employer's careers page still shows dayforce and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("dayforce")
