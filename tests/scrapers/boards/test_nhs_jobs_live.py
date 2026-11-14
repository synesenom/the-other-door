"""Live smoke tests for NHS Jobs (jobs.nhs.uk), one per mode (#19): "nurse" in London, newest first.

Opt-in (marked `live`): fetches the real search pages and ads over plain HTTP. Run with `./scripts/run-test.sh --live`.
NHS search is loose (a "project manager" page can be all nurses and doctors), so the search is for what NHS Jobs always
lists in London. A refusal or challenge page (`nhs_jobs._Pushback`) is not reached.
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.boards import nhs_jobs
from door.scrapers.http_client import PoliteSession
from live_utils import (
    NONSENSE_KEYWORD as KW, assert_contract, assert_listing, assert_page2, assert_zero_hits, drain_zero_hit_state,
    fail, not_reached, probe_sized,
)

CONFIG = {"search_keywords": ["nurse"], "topic_terms": ["nurse*"], "location": "London"}
_KEYWORD = CONFIG["search_keywords"][0]


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=nhs_jobs._HEADERS)


def _get(session: PoliteSession, url: str) -> str:
    try:
        return nhs_jobs._get(session, url)
    except nhs_jobs._Pushback as exc:
        not_reached("nhs_jobs", str(exc))


def _cards(session: PoliteSession, page: int) -> list[dict]:
    cards = nhs_jobs._parse_cards(_get(session, nhs_jobs._search_url(_KEYWORD, CONFIG["location"], page)))
    assert cards is not None, fail("nhs_jobs", "page2" if page > 1 else "details", "no search results block")
    return cards


def _postings(cards: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [nhs_jobs._posting(c, nhs_jobs._card_text(c), c["posted"], now) for c in cards]


@pytest.mark.live
def test_nhs_jobs_listing_live():
    assert_listing("nhs_jobs", nhs_jobs, CONFIG)


@pytest.mark.live
def test_nhs_jobs_page2_live():
    with probe_sized("nhs_jobs", "page2"):
        session = _session()
        pages = [_cards(session, n) for n in (1, 2)]
    assert_page2("nhs_jobs", _postings(pages[0]), _postings(pages[1]), CONFIG)


@pytest.mark.live
def test_nhs_jobs_details_live():
    """Two ads' pages: the summary, duties and job description, the exact date and the job's own place."""
    with probe_sized("nhs_jobs", "details"):
        session = _session()
        cards = _cards(session, 1)
        assert cards, fail("nhs_jobs", "details", "no results to open")
        now = datetime.now(timezone.utc)
        postings = []
        for card in cards[:2]:
            detail = nhs_jobs._parse_detail(_get(session, card["url"]))
            assert detail is not None, fail("nhs_jobs", "details", f"no job description on {card['url']}")
            if detail["location"]:
                card = {**card, "location": detail["location"]}
            postings.append(nhs_jobs._posting(card, detail["description"], detail["posted"] or card["posted"], now))
    assert_contract("nhs_jobs", postings, "details", config=CONFIG, locations=True)


@pytest.mark.live
def test_nhs_jobs_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("nhs_jobs")
    with probe_sized("nhs_jobs", "listing"):
        postings = nhs_jobs.scrape({"search_keywords": [KW], "location": "London", "max_pages_per_keyword": 1})
    assert_zero_hits("nhs_jobs", postings)
