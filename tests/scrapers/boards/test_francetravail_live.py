"""Live smoke tests for France Travail (candidat.francetravail.fr), one per mode (#19): "chef de projet" in Paris,
page 1, page 2 (``range=20-39``), two ads' description JSON and the zero-hit answer.

Opt-in (marked `live`): hits the real site. Run with `./scripts/run-test.sh --live`.
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.boards import francetravail as ft
from door.scrapers.http_client import PoliteSession
from live_utils import (
    NONSENSE_KEYWORD as KW, assert_contract, assert_listing, assert_page2, assert_zero_hits, drain_zero_hit_state,
    probe_sized,
)

KEYWORD = "chef de projet"
CONFIG = {"search_keywords": [KEYWORD], "location": "Paris", "max_pages_per_keyword": 1}
_INSEE = ft._insee_code("Paris")


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=ft._HEADERS)


def _cards(session, page: int) -> list[dict]:
    html = session.get(ft._search_url(KEYWORD, _INSEE, ft._MAX_EMISSION, page)).text
    assert ft._is_results_page(html), f"francetravail: page {page} has no result list"
    return ft._parse_cards(html)


def _postings(cards: list[dict]) -> list[dict]:
    now, scraped_at = datetime.now(), datetime.now(timezone.utc)
    return [ft._card_posting(c, now, scraped_at) for c in cards]


@pytest.mark.live
def test_francetravail_listing_live():
    """The cards carry a ~200 character teaser, not the ad, so no descriptions."""
    assert_listing("francetravail", ft, CONFIG)


@pytest.mark.live
def test_francetravail_page2_live():
    with probe_sized("francetravail", "page2"):
        session = _session()
        pages = [_cards(session, n) for n in (1, 2)]
    assert_page2("francetravail", _postings(pages[0]), _postings(pages[1]), CONFIG)


@pytest.mark.live
def test_francetravail_details_live():
    """Two ads' description JSON (`api-descriptifoffre`), the text the ad page loads."""
    with probe_sized("francetravail", "details"):
        session = _session()
        cards = _cards(session, 1)
        assert cards, "francetravail [details]: no results to open"
        now, scraped_at = datetime.now(), datetime.now(timezone.utc)
        postings = []
        for card in cards[:2]:
            detail = ft._parse_detail(session.get(ft._detail_url(card["id"]), headers=ft._JSON_HEADERS).text)
            assert detail is not None, f"francetravail [details]: no ad text at {ft._detail_url(card['id'])}"
            postings.append(ft._posting(card, detail, now, scraped_at))
    assert_contract("francetravail", postings, "details", config=CONFIG)


@pytest.mark.live
def test_francetravail_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("francetravail")
    with probe_sized("francetravail", "listing"):
        postings = ft.scrape({"search_keywords": [KW], "location": "Paris", "max_pages_per_keyword": 1})
    assert_zero_hits("francetravail", postings)
