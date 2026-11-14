"""Live smoke tests for the SmartRecruiters postings API, one per mode (#19): Inter IKEA Group's postings, and a real
employer's careers page still detected as SmartRecruiters.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import smartrecruiters
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_detects, assert_listing, assert_page2, probe_sized

_COMPANY = "interikeagroup"
CONFIG = {"smartrecruiters_companies": [_COMPANY], "location": "Stockholm"}
_LIMIT = 20  # the probe's page size


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=smartrecruiters._HEADERS)


def _page(session: PoliteSession, offset: int) -> list[dict]:
    data = session.get(f"{smartrecruiters._API}/{_COMPANY}/postings", params={"limit": _LIMIT, "offset": offset},
                       headers=smartrecruiters._HEADERS).json()
    return smartrecruiters._items(data.get("content"))


@pytest.mark.live
def test_smartrecruiters_listing_live():
    """Page 1 of the listing: title, place, date and link (the text is on the posting's own answer)."""
    assert_listing("smartrecruiters", smartrecruiters, CONFIG)


@pytest.mark.live
def test_smartrecruiters_page2_live():
    with probe_sized("smartrecruiters", "page2"):
        session = _session()
        pages = [_page(session, offset) for offset in (0, _LIMIT)]
    now = datetime.now(timezone.utc)
    page1, page2 = ([smartrecruiters._to_posting(i, None, _COMPANY, now) for i in page] for page in pages)
    assert_page2("smartrecruiters", page1, page2, CONFIG)


@pytest.mark.live
def test_smartrecruiters_details_live():
    """Two postings' own answers: `jobAd.sections`, the posting and apply links."""
    with probe_sized("smartrecruiters", "details"):
        session = _session()
        items = _page(session, 0)
        assert items, "smartrecruiters [details]: no postings to open"
        now = datetime.now(timezone.utc)
        postings = []
        for item in items[:2]:
            detail = session.get(f"{smartrecruiters._API}/{_COMPANY}/postings/{item['id']}",
                                 headers=smartrecruiters._HEADERS).json()
            postings.append(smartrecruiters._to_posting(item, detail, _COMPANY, now))
    assert_contract("smartrecruiters", postings, "details", config=CONFIG)


@pytest.mark.live
def test_smartrecruiters_detection_live():
    """A real employer's careers page still shows smartrecruiters and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("smartrecruiters")
