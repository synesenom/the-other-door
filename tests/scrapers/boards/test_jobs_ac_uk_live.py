"""Live smoke tests for jobs.ac.uk (academic jobs), one per mode (#19): "research associate" in London, newest first.

Opt-in (marked `live`): fetches the real search pages and ads over plain HTTP. Run with `./scripts/run-test.sh --live`.
A refusal or challenge page (`jobs_ac_uk._Pushback`) is not reached.
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.boards import jobs_ac_uk
from door.scrapers.http_client import PoliteSession
from live_utils import (
    NONSENSE_KEYWORD as KW, assert_contract, assert_listing, assert_page2, assert_zero_hits, drain_zero_hit_state,
    fail, not_reached, probe_sized,
)

CONFIG = {"search_keywords": ["research associate"], "topic_terms": ["research*", "postdoc*"], "location": "London"}
_KEYWORD = CONFIG["search_keywords"][0]


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=jobs_ac_uk._HEADERS)


def _get(session: PoliteSession, url: str) -> str:
    try:
        return jobs_ac_uk._get(session, url)
    except jobs_ac_uk._Pushback as exc:
        not_reached("jobs_ac_uk", str(exc))


def _cards(session: PoliteSession, page: int) -> list[dict]:
    cards = jobs_ac_uk._parse_cards(_get(session, jobs_ac_uk._search_url(_KEYWORD, CONFIG["location"], page)))
    assert cards is not None, fail("jobs_ac_uk", "page2" if page > 1 else "details", "no search results block")
    return cards


def _postings(cards: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [jobs_ac_uk._posting(c, jobs_ac_uk._card_text(c), jobs_ac_uk._card_date(c), now) for c in cards]


@pytest.mark.live
def test_jobs_ac_uk_listing_live():
    assert_listing("jobs_ac_uk", jobs_ac_uk, CONFIG)


@pytest.mark.live
def test_jobs_ac_uk_page2_live():
    with probe_sized("jobs_ac_uk", "page2"):
        session = _session()
        pages = [_cards(session, n) for n in (1, 2)]
    assert_page2("jobs_ac_uk", _postings(pages[0]), _postings(pages[1]), CONFIG)


@pytest.mark.live
def test_jobs_ac_uk_details_live():
    """Two ads' pages: the full description and exact date in their schema.org ``JobPosting`` JSON-LD."""
    with probe_sized("jobs_ac_uk", "details"):
        session = _session()
        cards = _cards(session, 1)
        assert cards, fail("jobs_ac_uk", "details", "no results to open")
        now = datetime.now(timezone.utc)
        postings = []
        for card in cards[:2]:
            detail = jobs_ac_uk._parse_detail(_get(session, card["url"]))
            assert detail is not None, fail("jobs_ac_uk", "details", f"no JobPosting JSON-LD on {card['url']}")
            postings.append(jobs_ac_uk._posting(card, detail["description"], detail["posted"] or jobs_ac_uk._card_date(card), now))
    assert_contract("jobs_ac_uk", postings, "details", config=CONFIG)


@pytest.mark.live
def test_jobs_ac_uk_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("jobs_ac_uk")
    with probe_sized("jobs_ac_uk", "listing"):
        postings = jobs_ac_uk.scrape({"search_keywords": [KW], "location": "London", "max_pages_per_keyword": 1})
    assert_zero_hits("jobs_ac_uk", postings)
