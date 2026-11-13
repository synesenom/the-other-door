"""Live smoke tests for Talentsoft career sites, one per mode (#19): AGRICA's list (``agrica-career.talent-soft.com``),
its RSS feed and two ad pages, and a real employer's careers page still detected as Talentsoft.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import talentsoft
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_detects, assert_listing, assert_page2, probe_sized

_ENTRY = "agrica-career.talent-soft.com"
CONFIG = {"talentsoft_hosts": [_ENTRY], "location": "Paris, France"}
_BASE = talentsoft._base(_ENTRY)


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0)


def _postings(name: str, cards: list[dict], texts: dict | None = None) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [talentsoft._to_posting(c, _BASE, name or _ENTRY, (texts or {}).get(c["id"], ""), now) for c in cards]


@pytest.mark.live
def test_talentsoft_listing_live():
    """Page 1 of the list: ten cards with title, place and day (the text is in the feed or on the ad)."""
    assert_listing("talentsoft", talentsoft, CONFIG)


@pytest.mark.live
def test_talentsoft_page2_live():
    with probe_sized("talentsoft", "page2"):
        session = _session()
        pages = [talentsoft.parse_list(session.get(f"{_BASE}{talentsoft._LIST_PATH}" + (f"?page={n}" if n > 1 else "")).text)
                 for n in (1, 2)]
    (_, name, page1), (_, _, page2) = pages
    assert_page2("talentsoft", _postings(name, page1), _postings(name, page2), CONFIG)


@pytest.mark.live
def test_talentsoft_details_live():
    """The texts: the RSS feed's (the newest ads), and two ad pages' (the rest)."""
    with probe_sized("talentsoft", "details", most=4):
        session = _session()
        _, name, cards = talentsoft.parse_list(session.get(f"{_BASE}{talentsoft._LIST_PATH}").text)
        assert cards, "talentsoft [details]: no ad cards on the list"
        feed = talentsoft.parse_feed(session.get(f"{_BASE}{talentsoft._RSS_PATH}").text)
        pages = {}
        for card in cards[:2]:
            page = talentsoft.parse_detail(session.get(card["url"] if card["url"].startswith("http") else f"{_BASE}{card['url']}").text)
            assert page is not None, f"talentsoft [details]: ad {card['id']} has no description"
            pages[card["id"]] = page["description"]
    assert_contract("talentsoft", _postings(name, cards[:2], pages), "details", config=CONFIG)
    in_feed = [c for c in cards if c["id"] in feed]
    assert in_feed, "talentsoft [details]: the RSS feed holds none of the newest ads on the list"
    assert_contract("talentsoft", _postings(name, in_feed, {i: ad["description"] for i, ad in feed.items()}),
                    "details", config=CONFIG)


@pytest.mark.live
def test_talentsoft_detection_live():
    """A real employer's careers page still shows talentsoft and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("talentsoft")
