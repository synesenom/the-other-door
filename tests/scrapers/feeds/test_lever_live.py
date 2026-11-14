"""Live smoke tests for the Lever postings API, one per mode (#19): Siteimprove, a Danish company on the EU host
(issue #227; its slug answers 404 on the US host first), and a real employer's careers page still detected as Lever.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import lever
from live_utils import assert_detects, assert_listing

CONFIG = {"lever_companies": ["siteimprove"], "location": "Copenhagen"}
NO_PAGE2 = "one answer of the postings API lists every job of a company"
NO_DETAILS = "the listing carries each ad's whole text (description, lists, additional)"


@pytest.mark.live
def test_lever_listing_live():
    assert_listing("lever", lever, CONFIG, descriptions=True)


@pytest.mark.live
def test_lever_detection_live():
    """A real employer's careers page still shows lever and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("lever")
