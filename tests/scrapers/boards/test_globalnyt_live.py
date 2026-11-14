"""Live smoke tests for Globalnyt (globalnyt.dk), one per mode (#19): its WordPress list of every ad and two ad pages.

Opt-in (marked `live`). The list carries each ad's full text and date but neither its employer nor its place (only an
ad's page names them), so the listing's contract leaves companies and locations out.
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.boards import globalnyt
from door.scrapers.http_client import PoliteSession
from live_utils import (
    NONSENSE_KEYWORD as KW, assert_contract, assert_listing, assert_zero_hits, drain_zero_hit_state, fail, probe_sized,
)

CONFIG = {"search_keywords": ["rådgiver"], "location": "Copenhagen"}
NO_PAGE2 = "one answer of the WordPress list (per_page=100) holds every ad on the board"


@pytest.mark.live
def test_globalnyt_listing_live():
    assert_listing("globalnyt", globalnyt, CONFIG, descriptions=True, locations=False, companies=False)


@pytest.mark.live
def test_globalnyt_details_live():
    """Two ads' pages: the employer (``Organisation``) and the place (``Sted``) the list does not name."""
    with probe_sized("globalnyt", "details"):
        session = PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0)
        ads = globalnyt._parse_list(session.get(globalnyt._LIST_URL).json())
        assert ads, fail("globalnyt", "details", "no ads to open")
        now = datetime.now(timezone.utc)
        postings = []
        for ad in ads[:2]:
            page = session.get(ad["url"]).text
            company = globalnyt._detail_field(page, "Organisation")
            assert company, fail("globalnyt", "details", f"no Organisation on {ad['url']}")
            postings.append(globalnyt._to_posting(ad, company, globalnyt._detail_field(page, "Sted"), now))
    assert_contract("globalnyt", postings, "details", config=CONFIG)


@pytest.mark.live
def test_globalnyt_zero_hits_live(monkeypatch):
    """The scraper sends no keyword (it reads every ad), so the list is narrowed by WordPress's own search to a
    keyword no ad contains: the empty list must come back as an answer, a quiet day, not a changed site (#19)."""
    monkeypatch.setattr(globalnyt, "_LIST_URL", f"{globalnyt._LIST_URL}&search={KW}")
    drain_zero_hit_state("globalnyt")
    with probe_sized("globalnyt", "listing"):
        postings = globalnyt.scrape({"search_keywords": [KW], "location": "Copenhagen"})
    assert_zero_hits("globalnyt", postings)
