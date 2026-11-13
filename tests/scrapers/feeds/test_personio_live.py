"""Live smoke tests for Personio's XML feed, one per mode (#19): PNO Group Europe's account, and a real employer's
careers page still detected as Personio.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import personio
from live_utils import assert_detects, assert_listing

CONFIG = {"personio_companies": ["pno-group-europe"], "location": "Paris, France"}
NO_PAGE2 = "one XML answer lists every open ad of an account"
NO_DETAILS = "the feed carries each ad's whole text (`jobDescriptions`)"


@pytest.mark.live
def test_personio_listing_live():
    """PNO Group Europe's feed: every field, the description too, comes with the list."""
    assert_listing("personio", personio, CONFIG, descriptions=True)


@pytest.mark.live
def test_personio_detection_live():
    """A real employer's careers page still shows personio and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("personio")
