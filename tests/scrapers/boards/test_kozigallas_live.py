"""Live smoke tests for KÖZSZOLGÁLLÁS (kozszolgallas.ksz.gov.hu, the Hungarian public-service job portal), one per
mode (#19): the search for "ápoló" (nurse), page 1, page 2 (``"page": 2`` of the list POST), two ad pages and the
zero-hit answer.

Opt-in (marked `live`): hits the real site. Run with `./scripts/run-test.sh --live`. The host's root certificate
(Microsec's e-Szigno RSA TLS Root CA 2025) is verified against the system's trust store: a machine whose store
lacks it fails the TLS handshake, which reads as not reached.
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.boards import kozigallas as kz
from live_utils import (
    NONSENSE_KEYWORD as KW, assert_contract, assert_listing, assert_page2, assert_zero_hits, drain_zero_hit_state,
    probe_sized,
)

KEYWORD = "ápoló"
CONFIG = {"search_keywords": [KEYWORD], "location": "Budapest", "max_pages_per_keyword": 1}


def _cards(session, page: int) -> list[dict]:
    html = session.post(kz._LIST_URL, data=kz._search_body(KEYWORD, page).encode("utf-8"), headers=kz._JSON).text
    assert kz._is_results_page(html), f"kozigallas: page {page} has no result list"
    return kz._parse_cards(html)


def _postings(cards: list[dict]) -> list[dict]:
    scraped_at = datetime.now(timezone.utc)
    return [kz._card_posting(c, scraped_at) for c in cards]


@pytest.mark.live
def test_kozigallas_listing_live():
    """A card has no posting date (only the application deadline; the ad page has it) and no text."""
    assert_listing("kozigallas", kz, CONFIG, dates=False)


@pytest.mark.live
def test_kozigallas_page2_live():
    with probe_sized("kozigallas", "page2"):
        session = kz._session(30, max_retries=0)
        pages = [_cards(session, n) for n in (1, 2)]
    assert_page2("kozigallas", _postings(pages[0]), _postings(pages[1]), CONFIG, dates=False)


@pytest.mark.live
def test_kozigallas_details_live():
    """Two ad pages: the whole call (``#jobAd``) and its planned publication day (``posted_at``)."""
    with probe_sized("kozigallas", "details"):
        session = kz._session(30, max_retries=0)
        cards = _cards(session, 1)
        assert cards, "kozigallas [details]: no results to open"
        scraped_at = datetime.now(timezone.utc)
        postings = []
        for card in cards[:2]:
            detail = kz._parse_detail(session.get(card["url"]).text)
            assert detail is not None, f"kozigallas [details]: no ad text on {card['url']}"
            postings.append(kz._posting(card, detail, scraped_at))
    assert_contract("kozigallas", postings, "details", config=CONFIG)


@pytest.mark.live
def test_kozigallas_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("kozigallas")
    with probe_sized("kozigallas", "listing"):
        postings = kz.scrape({"search_keywords": [KW], "location": "Budapest", "max_pages_per_keyword": 1})
    assert_zero_hits("kozigallas", postings)
