"""Live smoke tests for Flatchr career sites, one per mode (#19): BELFOR France's (``careers.flatchr.io/company/belfor``;
Flatchr's own site would name the platform as the employer), and a real employer's careers page still detected as
Flatchr.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import flatchr
from live_utils import assert_detects, assert_listing

CONFIG = {"flatchr_companies": ["belfor"], "location": "Paris"}
NO_PAGE2 = "one answer of the company's JSON list holds every open ad (`page` and `limit` change nothing)"
NO_DETAILS = "the list carries each ad's whole text (description, mission, profile)"


@pytest.mark.live
def test_flatchr_listing_live():
    assert_listing("flatchr", flatchr, CONFIG, descriptions=True)


@pytest.mark.live
def test_flatchr_detection_live():
    """A real employer's careers page still shows flatchr and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("flatchr")
