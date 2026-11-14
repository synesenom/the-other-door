"""Live smoke tests for the Ashby job-board API, one per mode (#19): Pleo's board, and a real employer's careers page
still detected as Ashby.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import ashby
from live_utils import assert_detects, assert_listing

CONFIG = {"ashby_companies": ["pleo"], "location": "Copenhagen"}
NO_PAGE2 = "one answer of the job-board API lists every job of a board"
NO_DETAILS = "the listing carries each ad's whole description (`descriptionPlain`)"


@pytest.mark.live
def test_ashby_listing_live():
    """Pleo's board: every field, the description too, comes with the list."""
    assert_listing("ashby", ashby, CONFIG, descriptions=True)


@pytest.mark.live
def test_ashby_detection_live():
    """A real employer's careers page still shows ashby and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("ashby")
