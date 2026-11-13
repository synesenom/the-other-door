"""Live smoke tests for career sites read through sitemaps and JobPosting markup, one per mode (#19): Publicis
Sapient's career site (issue #232), and a real employer's careers page still detected as one.

- listing: the job sitemap and its newest job page's JobPosting markup (`probe`);
- details: the job sitemap and the markup of its two newest job pages.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import career_sites
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_detects, assert_listing, fail, probe_sized

CONFIG = {"career_sites": ["careers.publicissapient.com"], "location": "London"}
NO_PAGE2 = "a site's job sitemaps list every job page at once"


@pytest.mark.live
def test_career_sites_listing_live():
    """The newest job page's markup carries the whole ad, its description too."""
    assert_listing("career_sites", career_sites, CONFIG, descriptions=True)


@pytest.mark.live
def test_career_sites_details_live():
    base = career_sites._base(CONFIG["career_sites"][0])
    host = base.split("://", 1)[1]
    with probe_sized("career_sites", "details"):
        session = PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=career_sites._HEADERS)
        urls = career_sites._job_urls(session, base, None)[:2]
        assert urls, fail("career_sites", "details", "no job pages in the site's sitemaps")
        now = datetime.now(timezone.utc)
        postings = []
        for url in urls:
            resp = career_sites._get(session, url)
            jobs = career_sites._job_postings_from_html(resp.text)
            assert jobs, fail("career_sites", "details", f"no JobPosting markup at {url}")
            postings.append(career_sites._to_posting(jobs[0], resp.url or url, host, now))
    assert_contract("career_sites", postings, "details", config=CONFIG)


@pytest.mark.live
def test_career_sites_detection_live():
    """A real employer's careers page still shows career_sites and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("career_sites")
