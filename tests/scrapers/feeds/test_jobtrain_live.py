"""Live smoke tests for Jobtrain career sites, one per mode (#19): Leigh Academies Trust on the shared host
(``www.jobtrain.co.uk/leighacademiestrust``), and a real employer's careers page still detected as Jobtrain.

- listing: the first ``_JobCard`` page (12 cards: title, place, link); it has no date (the ad page does);
- page2: the next cards (``Skip=`` the first page's count);
- details: two ads' pages, whose JSON-LD carries the text, the date and the place.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import jobtrain
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_detects, assert_listing, assert_page2, fail, probe_sized

CONFIG = {"jobtrain_companies": ["leighacademiestrust"], "location": "London"}
_BASE, _LABEL = jobtrain._target("leighacademiestrust")


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=jobtrain._HEADERS)


def _postings(cards: list[dict], ads=None) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [jobtrain._to_posting(c, (ads or {}).get(c["id"]), _BASE, _LABEL, "", now) for c in cards]


@pytest.mark.live
def test_jobtrain_listing_live():
    assert_listing("jobtrain", jobtrain, CONFIG, dates=False)


@pytest.mark.live
def test_jobtrain_page2_live():
    with probe_sized("jobtrain", "page2"):
        session = _session()
        _total, first = jobtrain.parse_cards(session.get(jobtrain._list_url(_BASE, 0)).text)
        _total, second = jobtrain.parse_cards(session.get(jobtrain._list_url(_BASE, len(first))).text)
    assert_page2("jobtrain", _postings(first), _postings(second), CONFIG, dates=False)


@pytest.mark.live
def test_jobtrain_details_live():
    with probe_sized("jobtrain", "details"):
        session = _session()
        _total, cards = jobtrain.parse_cards(session.get(jobtrain._list_url(_BASE, 0)).text)
        cards = cards[:2]
        assert cards, fail("jobtrain", "details", "no cards to open")
        ads = {c["id"]: jobtrain.parse_ad(session.get(f"{_BASE}/Job/JobDetail?JobId={c['id']}").text) for c in cards}
    assert all(ads.values()), fail("jobtrain", "details", f"an ad page without its JSON-LD: {list(ads)}")
    assert_contract("jobtrain", _postings(cards, ads), "details", config=CONFIG)


@pytest.mark.live
def test_jobtrain_detection_live():
    """A real employer's careers page still shows jobtrain and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("jobtrain")
