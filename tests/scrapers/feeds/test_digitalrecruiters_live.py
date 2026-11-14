"""Live smoke tests for Digitalrecruiters career sites, one per mode (#19): Franprix's, a small tenant (issue #561),
and a real employer's careers page still detected as Digitalrecruiters.

- listing: the site's sitemap, every ad's link and its slug's words; it names no place and no date (the ad page does);
- details: the sitemap and two ads' pages, whose JSON-LD carries the text (the tenant asks a 10 s Crawl-delay).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import digitalrecruiters as dr
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_detects, assert_listing, fail, probe_sized

CONFIG = {"digitalrecruiters_sites": ["recrutement.franprix.fr"], "location": "Paris"}
NO_PAGE2 = "the site's sitemap lists every open ad at once"
_ENTRY = CONFIG["digitalrecruiters_sites"][0]


@pytest.mark.live
def test_digitalrecruiters_listing_live():
    assert_listing("digitalrecruiters", dr, CONFIG, locations=False, dates=False)


@pytest.mark.live
def test_digitalrecruiters_details_live():
    with probe_sized("digitalrecruiters", "details"):
        session = PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=dr._HEADERS)
        _children, ads = dr.parse_sitemap(session.get(f"{dr._base(_ENTRY)}/sitemap.xml").text)
        items = dr._rank(ads, CONFIG)[:2]
        assert items, fail("digitalrecruiters", "details", "no ads in the sitemap")
        pages = {i["id"]: dr.parse_ad(session.get(i["url"]).text) for i in items}
    assert all(pages.values()), fail("digitalrecruiters", "details", f"an ad without its JSON-LD: {[i['url'] for i in items]}")
    now = datetime.now(timezone.utc)
    postings = [dr._to_posting(i, pages[i["id"]], _ENTRY, "", now) for i in items]
    assert_contract("digitalrecruiters", postings, "details", config=CONFIG)


@pytest.mark.live
def test_digitalrecruiters_detection_live():
    """A real employer's careers page still shows digitalrecruiters and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("digitalrecruiters")
