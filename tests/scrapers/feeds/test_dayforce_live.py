"""Live smoke tests for the Dayforce candidate portal, one per mode (#19): Natus Sensory's portal, and a real
employer's careers page still detected as Dayforce.

- page2: the portal's search from ``paginationStart`` 0 and 25 (each search asks its CSRF token first).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import dayforce
from door.scrapers.http_client import PoliteSession
from live_utils import assert_detects, assert_listing, assert_page2, probe_sized

CONFIG = {"dayforce_companies": ["natus/CANDIDATEPORTALSENSORY"], "location": "London"}
NO_DETAILS = "the search carries each ad's whole description (`jobDescription`)"


@pytest.mark.live
def test_dayforce_listing_live():
    """Page 1 of the portal's search: every field, the description too."""
    assert_listing("dayforce", dayforce, CONFIG, descriptions=True)


@pytest.mark.live
def test_dayforce_page2_live():
    client, portal = dayforce._portal(CONFIG["dayforce_companies"][0])
    with probe_sized("dayforce", "page2", most=4):   # a token and a search a page
        session = PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=dayforce._HEADERS)
        first = dayforce._search(session, client, portal, 0)
        second = dayforce._search(session, client, portal, len(first.get("jobPostings") or []))
    now = datetime.now(timezone.utc)
    pages = [[dayforce._to_posting(i, client, portal, now) for i in dayforce._items(p)] for p in (first, second)]
    assert_page2("dayforce", pages[0], pages[1], CONFIG, descriptions=True)


@pytest.mark.live
def test_dayforce_detection_live():
    """A real employer's careers page still shows dayforce and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("dayforce")
