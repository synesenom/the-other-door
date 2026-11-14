"""Live smoke tests for Akademikernes Jobbank (jobbank.dk), one per mode (#19): the search for "analyst".

Opt-in (marked `live`): fetches the real search pages and ads over plain HTTP. Run with `./scripts/run-test.sh --live`.
A Cloudflare refusal or challenge (`jobbank._Pushback`) is not reached.
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.boards import jobbank
from door.scrapers.http_client import PoliteSession
from live_utils import (
    NONSENSE_KEYWORD as KW, assert_contract, assert_listing, assert_page2, assert_zero_hits, drain_zero_hit_state,
    fail, not_reached, probe_sized,
)

CONFIG = {"search_keywords": ["analyst"], "location": "Copenhagen"}
_KEYWORD = CONFIG["search_keywords"][0]


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=jobbank._HEADERS)


def _get(session: PoliteSession, url: str) -> str:
    try:
        return jobbank._get(session, url)
    except jobbank._Pushback as exc:
        not_reached("jobbank", str(exc))


def _cards(session: PoliteSession, page: int) -> list[dict]:
    return jobbank._parse_cards(_get(session, jobbank._search_url(_KEYWORD, page)))


def _postings(cards: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [jobbank._card_posting(c, now) for c in cards]


@pytest.mark.live
def test_jobbank_listing_live():
    assert_listing("jobbank", jobbank, CONFIG)


@pytest.mark.live
def test_jobbank_page2_live():
    with probe_sized("jobbank", "page2"):
        session = _session()
        pages = [_cards(session, n) for n in (1, 2)]
    assert_page2("jobbank", _postings(pages[0]), _postings(pages[1]), CONFIG)


@pytest.mark.live
def test_jobbank_details_live():
    """Two ads' pages: their schema.org ``JobPosting`` JSON-LD (description, date, employer, place)."""
    with probe_sized("jobbank", "details"):
        session = _session()
        cards = _cards(session, 1)
        assert cards, fail("jobbank", "details", "no results to open")
        now = datetime.now(timezone.utc)
        postings = []
        for card in cards[:2]:
            detail = jobbank._parse_detail(_get(session, card["url"]))
            assert detail is not None, fail("jobbank", "details", f"no JobPosting JSON-LD on {card['url']}")
            postings.append(jobbank._posting(card, detail, now))
    assert_contract("jobbank", postings, "details", config=CONFIG)


@pytest.mark.live
def test_jobbank_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("jobbank")
    with probe_sized("jobbank", "listing"):
        postings = jobbank.scrape({"search_keywords": [KW], "location": "Copenhagen", "max_pages_per_keyword": 1})
    assert_zero_hits("jobbank", postings)
