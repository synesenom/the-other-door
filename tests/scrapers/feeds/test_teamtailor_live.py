"""Live smoke tests for Teamtailor's public jobs feed, one per mode (#19): Storytel's board, and a real employer's
careers page (Templafy, a Danish company) still detected as Teamtailor.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import teamtailor
from live_utils import assert_detects, assert_listing

CONFIG = {"teamtailor_companies": ["storytel"], "location": "Stockholm"}
NO_PAGE2 = "`jobs.json` answers every job of a board on its first page (a further page adds none)"
NO_DETAILS = "each feed item carries the ad's whole text (`content_html`)"


@pytest.mark.live
def test_teamtailor_listing_live():
    """Storytel's board: every field, the description too, comes with the list."""
    assert_listing("teamtailor", teamtailor, CONFIG, descriptions=True)


@pytest.mark.live
def test_teamtailor_detection_live():
    """A real employer's careers page still shows teamtailor and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("teamtailor")
