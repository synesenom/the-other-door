"""Live smoke tests for Reed (reed.co.uk), one per mode (#19): the search for "project manager" in London.

Opt-in (marked `live`): fetches the real search pages and ads over plain HTTP. Run with `./scripts/run-test.sh --live`.
A refusal or challenge page (`reed._Pushback`) is not reached.
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.boards import reed
from door.scrapers.http_client import PoliteSession
from live_utils import (
    NONSENSE_KEYWORD as KW, assert_contract, assert_listing, assert_page2, assert_zero_hits, drain_zero_hit_state,
    fail, not_reached, probe_sized,
)

CONFIG = {"search_keywords": ["project manager"], "topic_terms": ["project*"], "location": "London"}
_KEYWORD = CONFIG["search_keywords"][0]


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=reed._HEADERS)


def _get(session: PoliteSession, url: str) -> str:
    try:
        return reed._get(session, url)
    except reed._Pushback as exc:
        not_reached("reed", str(exc))


def _cards(session: PoliteSession, page: int) -> list[dict]:
    parsed = reed._parse_results(_get(session, reed._search_url(_KEYWORD, CONFIG["location"], page)))
    assert parsed is not None, fail("reed", "page2" if page > 1 else "details", "no __NEXT_DATA__ searchResults")
    return [c for c in (reed._card(j) for j in parsed[1]) if c]


def _postings(cards: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [reed._posting(c, c["snippet"], now) for c in cards]


@pytest.mark.live
def test_reed_listing_live():
    assert_listing("reed", reed, CONFIG)


@pytest.mark.live
def test_reed_page2_live():
    with probe_sized("reed", "page2"):
        session = _session()
        pages = [_cards(session, n) for n in (1, 2)]
    assert_page2("reed", _postings(pages[0]), _postings(pages[1]), CONFIG)


@pytest.mark.live
def test_reed_details_live():
    """Two ads' pages: the full description in their schema.org ``JobPosting`` JSON-LD."""
    with probe_sized("reed", "details"):
        session = _session()
        cards = _cards(session, 1)
        assert cards, fail("reed", "details", "no results to open")
        now = datetime.now(timezone.utc)
        postings = []
        for card in cards[:2]:
            description = reed._parse_description(_get(session, card["url"]))
            assert description, fail("reed", "details", f"no JobPosting JSON-LD on {card['url']}")
            postings.append(reed._posting(card, description, now))
    assert_contract("reed", postings, "details", config=CONFIG)


@pytest.mark.live
def test_reed_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("reed")
    with probe_sized("reed", "listing"):
        postings = reed.scrape({"search_keywords": [KW], "location": "London", "max_pages_per_keyword": 1})
    assert_zero_hits("reed", postings)
