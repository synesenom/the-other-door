"""Live smoke tests for Pinpoint's public career-site feed, one per mode (#19): Factbird, and a real employer's
careers page still detected as Pinpoint.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import pinpoint
from live_utils import assert_detects, assert_listing

CONFIG = {"pinpoint_companies": ["factbird"], "location": "Copenhagen"}
NO_PAGE2 = "one answer of `postings.json` lists every posting of a career site"
NO_DETAILS = "the feed carries each posting's whole text (description, responsibilities, skills, benefits)"


@pytest.mark.live
def test_pinpoint_listing_live():
    """Factbird's feed, descriptions included; `dates=False`: the feed carries no publish date."""
    assert_listing("pinpoint", pinpoint, CONFIG, descriptions=True, dates=False)


@pytest.mark.live
def test_pinpoint_detection_live():
    """A real employer's careers page still shows pinpoint and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("pinpoint")
