"""Live smoke tests for Recman career sites, one per mode (#19): Jobconnect Sweden's sitemap and two of its ads
(in Swedish), and a real employer's careers page still detected as Recman.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import recman
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_detects, assert_listing, probe_sized

_ENTRY = "jobconnectsverige"
CONFIG = {"recman_companies": [_ENTRY], "location": "Stockholm"}
NO_PAGE2 = "one sitemap lists every open job of a career site"


@pytest.mark.live
def test_recman_listing_live():
    """The sitemap: job links only (`locations=False`, `dates=False`: the titles, places and dates are on the ads)."""
    assert_listing("recman", recman, CONFIG, locations=False, dates=False)


@pytest.mark.live
def test_recman_details_live():
    """Two ads' pages: their JSON-LD `JobPosting`."""
    with probe_sized("recman", "details"):
        session = PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=recman._HEADERS)
        base = recman._base(_ENTRY)
        jobs = recman._job_links(session.get(f"{base}/sitemap.xml").text)
        assert jobs, "recman [details]: no job links in the sitemap"
        now = datetime.now(timezone.utc)
        postings = []
        for job in jobs[:2]:
            ad = recman._parse_detail(session.get(job["url"]).text)
            assert ad is not None, f"recman [details]: {job['url']} has no JSON-LD JobPosting"
            postings.append(recman._to_posting(job, ad, ad["organization"] or _ENTRY, now))
    assert_contract("recman", postings, "details", config=CONFIG)


@pytest.mark.live
def test_recman_detection_live():
    """A real employer's careers page still shows recman and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("recman")
