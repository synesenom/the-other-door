"""Live smoke tests for the Greenhouse boards API, one per mode (#19): Trustpilot's board, a Danish company, and a
real employer's careers page still detected as Greenhouse.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import greenhouse
from live_utils import assert_detects, assert_listing

CONFIG = {"greenhouse_boards": ["trustpilot"], "location": "Copenhagen"}
NO_PAGE2 = "one answer of the boards API lists every job of a board"
NO_DETAILS = "the listing carries each ad's whole description (`content=true`)"


@pytest.mark.live
def test_greenhouse_listing_live():
    """Trustpilot's board: every field, the description too, comes with the list."""
    assert_listing("greenhouse", greenhouse, CONFIG, descriptions=True)


@pytest.mark.live
def test_greenhouse_detection_live():
    """A real employer's careers page still shows greenhouse and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("greenhouse")
