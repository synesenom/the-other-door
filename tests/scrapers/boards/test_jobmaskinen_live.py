"""Live smoke tests for Jobmaskinen (job.jobmaskinen.dk), one per mode (#19): the title search for "elektriker",
page 1, page 2 (``offset=10``), two ads' pages (their ``JobPosting`` JSON-LD) and the zero-hit answer.

Opt-in (marked `live`): hits the real site. Run with `./scripts/run-test.sh --live`.
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.boards import jobmaskinen
from door.scrapers.http_client import PoliteSession
from live_utils import (
    NONSENSE_KEYWORD as KW, assert_contract, assert_listing, assert_page2, assert_zero_hits, drain_zero_hit_state,
    probe_sized,
)

KEYWORD = "elektriker"
CONFIG = {"search_keywords": [KEYWORD], "location": "Copenhagen"}


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0)


def _cards(session, page: int) -> list[dict]:
    cards, _ = jobmaskinen._parse_cards(jobmaskinen._get(session, jobmaskinen._search_url(KEYWORD, page)))
    return cards


def _postings(cards: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [jobmaskinen._posting(card, None, now) for card in cards]


@pytest.mark.live
def test_jobmaskinen_listing_live():
    """The cards carry no text (the job type stands in), so no descriptions."""
    assert_listing("jobmaskinen", jobmaskinen, CONFIG)


@pytest.mark.live
def test_jobmaskinen_page2_live():
    with probe_sized("jobmaskinen", "page2"):
        session = _session()
        pages = [_cards(session, n) for n in (1, 2)]
    assert_page2("jobmaskinen", _postings(pages[0]), _postings(pages[1]), CONFIG)


@pytest.mark.live
def test_jobmaskinen_details_live():
    with probe_sized("jobmaskinen", "details"):
        session = _session()
        cards = _cards(session, 1)
        assert cards, "jobmaskinen [details]: no results to open"
        now = datetime.now(timezone.utc)
        postings = []
        for card in cards[:2]:
            url = jobmaskinen._job_url(card["platform_id"])
            detail = jobmaskinen._parse_detail(jobmaskinen._get(session, url))
            assert detail is not None, f"jobmaskinen [details]: no JobPosting data on {url}"
            postings.append(jobmaskinen._posting(card, detail, now))
    assert_contract("jobmaskinen", postings, "details", config=CONFIG)


@pytest.mark.live
def test_jobmaskinen_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("jobmaskinen")
    with probe_sized("jobmaskinen", "listing"):
        postings = jobmaskinen.scrape({"search_keywords": [KW], "location": "Copenhagen"})
    assert_zero_hits("jobmaskinen", postings)
