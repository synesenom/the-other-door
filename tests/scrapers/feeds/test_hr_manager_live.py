"""Live smoke tests for Talentech HR-Manager's public job feed, one per mode (#19): Region Hovedstaden (``regionh``),
and a real employer's careers page still detected as HR-Manager.

- page2: the feed in pages of `_TAKE` positions (the scraper takes 100), ``skip`` 0 and `_TAKE`.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import hr_manager
from door.scrapers.http_client import PoliteSession
from live_utils import assert_detects, assert_listing, assert_page2, probe_sized

CONFIG = {"hr_manager_aliases": ["regionh"], "location": "Copenhagen"}
NO_DETAILS = "the feed carries each position's ad (`incads=true`)"
_TAKE = 10


@pytest.mark.live
def test_hr_manager_listing_live():
    """Page 1 of the feed: every field, the ad's text too (a position posted without an ad has none)."""
    assert_listing("hr_manager", hr_manager, CONFIG, descriptions=True)


@pytest.mark.live
def test_hr_manager_page2_live():
    with probe_sized("hr_manager", "page2"):
        session = PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=hr_manager._HEADERS)
        pages = [hr_manager._page(session, "regionh", skip, _TAKE) for skip in (0, _TAKE)]
    now = datetime.now(timezone.utc)
    postings = [[hr_manager._to_posting(i, "regionh", p.get("CustomerName") or "regionh", now)
                 for i in p.get("Items") or [] if i.get("Id") is not None] for p in pages]
    assert_page2("hr_manager", postings[0], postings[1], CONFIG, descriptions=True)


@pytest.mark.live
def test_hr_manager_detection_live():
    """A real employer's careers page still shows hr_manager and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("hr_manager")
