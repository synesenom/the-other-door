"""Live smoke tests for the Recruitee careers API, one per mode (#19): Famly, and a real employer's careers page
still detected as Recruitee.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import recruitee
from live_utils import assert_detects, assert_listing

CONFIG = {"recruitee_companies": ["famly"], "location": "Copenhagen"}
NO_PAGE2 = "one answer of `/api/offers/` lists every published offer"
NO_DETAILS = "the API carries each offer's whole description and requirements"


@pytest.mark.live
def test_recruitee_listing_live():
    """Famly's offers: every field, the description too, comes with the list."""
    assert_listing("recruitee", recruitee, CONFIG, descriptions=True)


@pytest.mark.live
def test_recruitee_detection_live():
    """A real employer's careers page still shows recruitee and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("recruitee")
