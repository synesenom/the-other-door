"""Live smoke tests for Taleez career sites, one per mode (#19): Donecle's job list (Toulouse) and two of its ads, and
a real employer's careers page still detected as Taleez.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import taleez
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_detects, assert_listing, probe_sized

_ENTRY = "donecle"
CONFIG = {"taleez_companies": [_ENTRY], "location": "Toulouse, France"}
NO_PAGE2 = "one answer of `/api/careez` lists every open job of a tenant"


@pytest.mark.live
def test_taleez_listing_live():
    """Donecle's list: title, place, date and link (the text is on the ad)."""
    assert_listing("taleez", taleez, CONFIG)


@pytest.mark.live
def test_taleez_details_live():
    """Two ads' pages on taleez.com: their JSON-LD description."""
    with probe_sized("taleez", "details"):
        session = PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=taleez._HEADERS)
        channel, jobs = taleez.parse_list(session.get(taleez.feed_url(_ENTRY)).text)
        assert jobs, "taleez [details]: no jobs on the list"
        now = datetime.now(timezone.utc)
        postings = []
        for job in jobs[:2]:
            ad = taleez.parse_ad(session.get(job["url"]).text)
            assert ad is not None, f"taleez [details]: {job['url']} has no JSON-LD JobPosting"
            postings.append(taleez._to_posting(job, ad["description"], channel or ad["organization"] or _ENTRY, now))
    assert_contract("taleez", postings, "details", config=CONFIG)


@pytest.mark.live
def test_taleez_detection_live():
    """A real employer's careers page still shows taleez and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("taleez")
