"""Live smoke tests for SuccessFactors RMK career sites, one per mode (#19): Novo Nordisk's ``sitemal.xml`` feed, and
a real employer's careers page still detected as SuccessFactors.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import successfactors
from live_utils import assert_detects, assert_listing

CONFIG = {"successfactors_companies": ["careers.novonordisk.com"], "location": "Copenhagen"}
NO_PAGE2 = "one answer of `sitemal.xml` lists every job of the career site"
NO_DETAILS = "each feed item carries the ad's text (`description`)"


@pytest.mark.live
def test_successfactors_listing_live():
    """Novo Nordisk's feed: the description comes with the list; `dates=False`: its items carry no ``pubDate``."""
    assert_listing("successfactors", successfactors, CONFIG, descriptions=True, dates=False)


@pytest.mark.live
def test_successfactors_detection_live():
    """A real employer's careers page still shows successfactors and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("successfactors")
