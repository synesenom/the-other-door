"""Live smoke tests for Choisir le service public (choisirleservicepublic.gouv.fr), one per mode (#19): "chef de
projet" in Île-de-France, page 1, page 2 (``page/2/``), two ad pages and the zero-hit answer.

Opt-in (marked `live`): hits the real site. Run with `./scripts/run-test.sh --live`.
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.boards import choisirleservicepublic as csp
from door.scrapers.http_client import PoliteSession
from live_utils import (
    NONSENSE_KEYWORD as KW, assert_contract, assert_listing, assert_page2, assert_zero_hits, drain_zero_hit_state,
    probe_sized,
)

KEYWORD = "chef de projet"
CONFIG = {"search_keywords": [KEYWORD], "location": "Paris", "max_pages_per_keyword": 1}
_PLACE = csp._location_id("Paris")


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=csp._HEADERS)


def _cards(session, page: int) -> list[dict]:
    html = session.get(csp._search_url(KEYWORD, _PLACE, page)).text
    assert csp._is_results_page(html), f"choisirleservicepublic: page {page} has no result list"
    return csp._parse_cards(html)


def _postings(cards: list[dict]) -> list[dict]:
    scraped_at = datetime.now(timezone.utc)
    return [csp._card_posting(c, scraped_at) for c in cards]


@pytest.mark.live
def test_choisirleservicepublic_listing_live():
    """The cards carry no text (title and employer stand in), so no descriptions."""
    assert_listing("choisirleservicepublic", csp, CONFIG)


@pytest.mark.live
def test_choisirleservicepublic_page2_live():
    with probe_sized("choisirleservicepublic", "page2"):
        session = _session()
        pages = [_cards(session, n) for n in (1, 2)]
    assert_page2("choisirleservicepublic", _postings(pages[0]), _postings(pages[1]), CONFIG)


@pytest.mark.live
def test_choisirleservicepublic_details_live():
    with probe_sized("choisirleservicepublic", "details"):
        session = _session()
        cards = _cards(session, 1)
        assert cards, "choisirleservicepublic [details]: no results to open"
        scraped_at = datetime.now(timezone.utc)
        postings = []
        for card in cards[:2]:
            detail = csp._parse_detail(session.get(card["url"]).text)
            assert detail is not None, f"choisirleservicepublic [details]: no ad text on {card['url']}"
            postings.append(csp._posting(card, detail, scraped_at))
    assert_contract("choisirleservicepublic", postings, "details", config=CONFIG)


@pytest.mark.live
def test_choisirleservicepublic_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("choisirleservicepublic")
    with probe_sized("choisirleservicepublic", "listing"):
        postings = csp.scrape({"search_keywords": [KW], "location": "Paris", "max_pages_per_keyword": 1})
    assert_zero_hits("choisirleservicepublic", postings)
