"""Live smoke test for Beetween: Giboire's career site on ``giboire.nous-recrutons.fr`` (open jobs, in French).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import beetween
from live_utils import assert_detects, assert_field_contract


@pytest.mark.live
def test_beetween_live_returns_valid_postings():
    postings = beetween.scrape({"beetween_companies": ["giboire"]})
    assert postings
    assert_field_contract("beetween", postings, mode="collect")


@pytest.mark.live
def test_beetween_detection_live():
    """A real employer's careers page still shows beetween and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("beetween")
