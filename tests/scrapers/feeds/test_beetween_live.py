"""Live smoke tests for Beetween, one per mode (#19): Giboire's career site on ``giboire.nous-recrutons.fr`` (open
jobs, in French), and a real employer's careers page still detected as Beetween.

- page2: the WordPress job list in pages of `_PAGE` jobs (the scraper asks 50), pages 1 and 2;
- details: two ads' own pages, whose JSON-LD carries the text, the place and the date.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import beetween
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_detects, assert_listing, assert_page2, fail, probe_sized

CONFIG = {"beetween_companies": ["giboire"], "location": "Rennes"}
_BASE = beetween._base("giboire")
_PAGE = 10  # jobs a page in the page2 test, so a small site has a second page


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=beetween._HEADERS)


def _postings(jobs: list[dict], ads=None) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [beetween._to_posting(j, (ads or {}).get(j["id"]), _BASE, "", now) for j in jobs]


@pytest.mark.live
def test_beetween_listing_live():
    """The job list's first page: title, link and date; it names no place (the ad page does)."""
    assert_listing("beetween", beetween, CONFIG, locations=False)


@pytest.mark.live
def test_beetween_page2_live(monkeypatch):
    monkeypatch.setattr(beetween, "_PER_PAGE", _PAGE)
    with probe_sized("beetween", "page2"):
        session = _session()
        pages = [beetween.parse_list(session.get(beetween._list_url(_BASE, n)).text) for n in (1, 2)]
    assert_page2("beetween", _postings(pages[0]), _postings(pages[1]), CONFIG, locations=False)


@pytest.mark.live
def test_beetween_details_live():
    """Two ads' pages: the JSON-LD JobPosting with the description, the place and the hiring organisation."""
    with probe_sized("beetween", "details"):
        session = _session()
        jobs = beetween.parse_list(session.get(beetween._list_url(_BASE, 1)).text)[:2]
        assert jobs, fail("beetween", "details", "no jobs to open")
        ads = {j["id"]: beetween.parse_ad(session.get(j["url"]).text) for j in jobs}
    assert all(ads.values()), fail("beetween", "details", f"an ad page without its JSON-LD: {[j['url'] for j in jobs]}")
    assert_contract("beetween", _postings(jobs, ads), "details", config=CONFIG)


@pytest.mark.live
def test_beetween_detection_live():
    """A real employer's careers page still shows beetween and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("beetween")
