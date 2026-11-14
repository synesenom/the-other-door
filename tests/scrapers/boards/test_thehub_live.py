"""Live smoke tests for The Hub (thehub.io), one per mode (#19): the Danish search for "developer".

Opt-in (marked `live`): fetches the real Nuxt-rendered pages over plain HTTP. Run with `./scripts/run-test.sh --live`.
The listing names no date (only an ad's page does), so its contract leaves dates out.
"""

from datetime import datetime, timezone

import pytest

from door.core.models import JobPosting
from door.scrapers.boards import thehub
from door.scrapers.http_client import PoliteSession
from live_utils import (
    NONSENSE_KEYWORD as KW, assert_contract, assert_listing, assert_page2, assert_zero_hits, drain_zero_hit_state,
    fail, probe_sized,
)

CONFIG = {"search_keywords": ["developer"], "location": "Copenhagen"}
_KEYWORD = CONFIG["search_keywords"][0]
_LISTING = ("state", "jobs", "jobs")


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0)


def _page(session: PoliteSession, n: int) -> list[dict]:
    jobs_obj = thehub._get_state(session, thehub._listing_url(_KEYWORD, thehub._country_code(CONFIG), n), _LISTING)
    assert jobs_obj is not None, fail("thehub", "page2" if n > 1 else "listing", "no window.__NUXT__.state.jobs.jobs")
    docs, _ = thehub._parse_listing_payload(jobs_obj)
    now = datetime.now(timezone.utc)
    return [thehub._listing_to_posting(d, now) for d in docs if d.get("id")]


@pytest.mark.live
def test_thehub_listing_live():
    assert_listing("thehub", thehub, CONFIG, dates=False)


@pytest.mark.live
def test_thehub_page2_live():
    with probe_sized("thehub", "page2"):
        session = _session()
        pages = [_page(session, n) for n in (1, 2)]
    assert_page2("thehub", pages[0], pages[1], CONFIG, dates=False)


@pytest.mark.live
def test_thehub_details_live():
    """Two ads' own pages (`state.jobs.job`): the description, the date and the company's own job page."""
    with probe_sized("thehub", "details"):
        session = _session()
        listed = _page(session, 1)
        assert listed, fail("thehub", "details", "no results to open")
        now = datetime.now(timezone.utc)
        postings = []
        for item in listed[:2]:
            url = thehub._job_url(item["platform_id"])
            parsed = thehub._parse_detail_payload(thehub._get_state(session, url, ("state", "jobs", "job")))
            assert parsed is not None, fail("thehub", "details", f"no state.jobs.job on {url}")
            postings.append(JobPosting(
                id=item["id"], title=parsed["title"], company=parsed["company"], location=parsed["location"], url=url,
                description=parsed["description"], source="thehub", scraped_at=now, platform_id=item["platform_id"],
                posted_at=parsed["posted_at"], apply_type="external" if parsed["apply_url"] else None,
                apply_url=parsed["apply_url"],
            ).model_dump(mode="json"))
    assert_contract("thehub", postings, "details", config=CONFIG, dates=True)


@pytest.mark.live
def test_thehub_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("thehub")
    with probe_sized("thehub", "listing"):
        postings = thehub.scrape({"search_keywords": [KW], "location": "Copenhagen"})
    assert_zero_hits("thehub", postings)
