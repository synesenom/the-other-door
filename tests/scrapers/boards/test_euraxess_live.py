"""Live smoke tests for EURAXESS (issue #431), one per mode (#19): Denmark's list of offers, over plain HTTP.

Opt-in (marked `live`). EURAXESS has no keyword search (the country's whole list is read, `NO_ZERO_HIT`), so the
one country read is Denmark: page 1, page 2 and two job pages' ``Offer Description``.
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.boards import euraxess
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_listing, assert_page2, fail, probe_sized

CONFIG = {"search_keywords": ["postdoc"], "topic_terms": [], "location": "Copenhagen, Denmark"}


def _session() -> PoliteSession:
    return PoliteSession(min_delay=1.0, max_delay=2.0, timeout=30, max_retries=0)


def _cards(session: PoliteSession, page: int) -> list[dict]:
    cards, _ = euraxess.parse_listing(euraxess._get(session, euraxess._SEARCH, params=euraxess._params("dk", page)).text)
    return cards


def _postings(cards: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [euraxess._to_posting(c, "", now) for c in cards]


@pytest.mark.live
def test_euraxess_listing_live():
    assert_listing("euraxess", euraxess, CONFIG)


@pytest.mark.live
def test_euraxess_page2_live():
    with probe_sized("euraxess", "page2"):
        session = _session()
        pages = [_cards(session, n) for n in (0, 1)]
    assert_page2("euraxess", _postings(pages[0]), _postings(pages[1]), CONFIG)


@pytest.mark.live
def test_euraxess_details_live():
    """Two job pages: the ``Offer Description`` after the ``Job Information`` block."""
    with probe_sized("euraxess", "details"):
        session = _session()
        cards = _cards(session, 0)
        assert cards, fail("euraxess", "details", "no offers to open")
        now = datetime.now(timezone.utc)
        postings = []
        for card in cards[:2]:
            description = euraxess.parse_detail(euraxess._get(session, card["url"]).text)
            assert description, fail("euraxess", "details", f"no Offer Description on {card['url']}")
            postings.append(euraxess._to_posting(card, description, now))
    assert_contract("euraxess", postings, "details", config=CONFIG)
