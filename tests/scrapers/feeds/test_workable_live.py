"""Live smoke tests for Workable, one per mode (#19). Workable is both a board and a feed:

- listing, page 2 and the zero-hit answer are its cross-company keyword search (jobs.workable.com: "engineer" in
  London; page 2 follows the answer's ``nextPageToken``);
- details is the feed side: a followed account (Dreamdata, a Danish company) read through the jobs widget
  (``details=true``), one request with every open job and its whole description, mapped as `collect` maps it;
- detection: a real employer's careers page still resolves to its account.

Opt-in (marked `live`): hits the real site. Run with `./scripts/run-test.sh --live`.
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import workable
from door.scrapers.http_client import PoliteSession
from live_utils import (
    NONSENSE_KEYWORD as KW, assert_contract, assert_detects, assert_listing, assert_page2, assert_zero_hits,
    drain_zero_hit_state, probe_sized,
)

KEYWORD, LOCATION = "engineer", "London"
CONFIG = {"search_keywords": [KEYWORD], "location": LOCATION, "max_pages_per_keyword": 1}
ACCOUNT = "dreamdata"


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=workable._HEADERS)


def _postings(page: dict) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [workable._to_posting(j, now) for j in page.get("jobs") or [] if isinstance(j, dict) and j.get("id")]


@pytest.mark.live
def test_workable_listing_live():
    """Page 1 of the keyword search; each result carries its description sections."""
    assert_listing("workable", workable, CONFIG, descriptions=True)


@pytest.mark.live
def test_workable_page2_live():
    with probe_sized("workable", "page2"):
        session = _session()
        first = workable._fetch_page(session, KEYWORD, LOCATION, None)
        token = first.get("nextPageToken")
        assert token, f"workable [page2]: no nextPageToken on page 1 ({first.get('totalSize')} results)"
        second = workable._fetch_page(session, KEYWORD, LOCATION, token)
    assert_page2("workable", _postings(first), _postings(second), CONFIG, descriptions=True)


@pytest.mark.live
def test_workable_details_live():
    """The feed side: a followed account's every job with its whole description, in one widget answer."""
    config = {"workable_companies": [ACCOUNT], "location": "Copenhagen"}
    with probe_sized("workable", "details"):
        data = _session().get(workable._WIDGET_URL.format(account=ACCOUNT), params={"details": "true"}).json()
    assert isinstance(data, dict) and isinstance(data.get("jobs"), list), \
        f"workable [details]: no `jobs` list in the widget answer for {ACCOUNT}"
    company = (data.get("name") or ACCOUNT).strip()
    now = datetime.now(timezone.utc)
    postings = [workable._widget_posting(j, company, now) for j in data["jobs"] if isinstance(j, dict) and j.get("shortcode")]
    assert_contract("workable", postings, "details", config=config, locations=True, dates=True)


@pytest.mark.live
def test_workable_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("workable")
    with probe_sized("workable", "listing"):
        postings = workable.scrape({"search_keywords": [KW], "location": LOCATION, "max_pages_per_keyword": 1,
                                    "_mode": "search"})
    assert_zero_hits("workable", postings)


@pytest.mark.live
def test_workable_detection_live():
    """A real employer's careers page still shows workable and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("workable")
