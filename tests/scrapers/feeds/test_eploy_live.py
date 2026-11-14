"""Live smoke tests for Eploy's public RSS data feed, one per mode (#19): Vitality (an ``eploy.net`` host), and a
real employer's careers page still detected as Eploy.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import eploy
from live_utils import assert_detects, assert_listing

CONFIG = {"eploy_hosts": ["vitalityweb.eploy.net"], "location": "London"}
NO_PAGE2 = "the RSS feed lists every open ad in one answer (no paging)"
NO_DETAILS = "the feed carries each ad's whole text; the ad page is not opened"


@pytest.mark.live
def test_eploy_listing_live():
    """The feed's first five ads (``RecordLimit=5``): every field, the text too."""
    assert_listing("eploy", eploy, CONFIG, descriptions=True)


@pytest.mark.live
def test_eploy_detection_live():
    """A real employer's careers page still shows eploy and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("eploy")
