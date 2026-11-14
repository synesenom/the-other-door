"""Live smoke tests for Arbetsförmedlingen (Platsbanken, the JobSearch API), one per mode (#19): "projektledare" in
Stockholm's municipalities, page 1, page 2 (``offset=100``) and the zero-hit answer.

Opt-in (marked `live`): hits the real API. Run with `./scripts/run-test.sh --live`.
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.boards import arbetsformedlingen as af
from door.scrapers.http_client import PoliteSession
from live_utils import (
    NONSENSE_KEYWORD as KW, assert_listing, assert_page2, assert_zero_hits, drain_zero_hit_state, probe_sized,
)

KEYWORD = "projektledare"
CONFIG = {"search_keywords": [KEYWORD], "location": "Stockholm"}
NO_DETAILS = "each hit of the search answer carries the whole ad (`description.text`)"


def _page(session, offset: int) -> list[dict]:
    hits, _total = af._parse_response(af._get(session, af._url(af._params(KEYWORD, af._municipalities(CONFIG), offset, None))))
    now = datetime.now(timezone.utc)
    return [p for p in (af._to_posting(h, now) for h in hits if af._is_live(h)) if p]


@pytest.mark.live
def test_arbetsformedlingen_listing_live():
    """Every field, the description too, comes with the search answer."""
    assert_listing("arbetsformedlingen", af, CONFIG, descriptions=True)


@pytest.mark.live
def test_arbetsformedlingen_page2_live():
    with probe_sized("arbetsformedlingen", "page2"):
        session = PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0)
        pages = [_page(session, offset) for offset in (0, af._PAGE_SIZE)]
    assert_page2("arbetsformedlingen", pages[0], pages[1], CONFIG, descriptions=True)


@pytest.mark.live
def test_arbetsformedlingen_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("arbetsformedlingen")
    with probe_sized("arbetsformedlingen", "listing"):
        postings = af.scrape({"search_keywords": [KW], "location": "Stockholm"})
    assert_zero_hits("arbetsformedlingen", postings)
