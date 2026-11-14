"""Live smoke tests for Jobindex, one per mode (#19): page 1, page 2, two ads and the zero-hit answer.

Opt-in (marked `live`): hits the real site. Run with `./scripts/run-test.sh --live`.
"""

from datetime import datetime, timezone

import pytest

from door.scrapers import drain_errors
from door.scrapers.boards import jobindex
from door.scrapers.http_client import PoliteSession
from live_utils import (
    NONSENSE_KEYWORD as KW, assert_contract, assert_listing, assert_page2, assert_zero_hits, drain_zero_hit_state,
    not_reached_if_refused, probe_sized,
)

CONFIG = {"search_keywords": ["projektleder"], "location": "Copenhagen"}
_AREA = jobindex._area_for_profile(CONFIG)


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=jobindex._HEADERS)


def _postings(page) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [jobindex._to_posting(r, jobindex._teaser_text(r.get("html", "")), now) for r in page.results if r.get("tid")]


@pytest.mark.live
def test_jobindex_listing_live():
    assert_listing("jobindex", jobindex, CONFIG)


@pytest.mark.live
def test_jobindex_page2_live():
    drain_errors("jobindex")
    with probe_sized("jobindex", "page2"):
        session = _session()
        pages = [jobindex._search_page(session, "projektleder", _AREA, n) for n in (1, 2)]
    not_reached_if_refused("jobindex", drain_errors("jobindex").get("jobindex", []))
    assert all(pages), "jobindex [page2]: a results page without its results block"
    assert_page2("jobindex", _postings(pages[0]), _postings(pages[1]), CONFIG)


@pytest.mark.live
def test_jobindex_details_live():
    """Two ads' own pages: Jobindex's or the employer's, read for the full description."""
    with probe_sized("jobindex", "details", most=8):
        session = _session()
        page = jobindex._search_page(session, "projektleder", _AREA, 1)
        assert page and page.results, "jobindex [details]: no results to open"
        now = datetime.now(timezone.utc)
        postings = []
        for raw in page.results[:2]:
            detail = jobindex._fetch_detail(session, raw["tid"], raw.get("html", ""))
            postings.append(jobindex._to_posting(raw, detail["description"], now, detail["apply_type"], detail["apply_url"]))
    assert_contract("jobindex", postings, "details", config=CONFIG)


@pytest.mark.live
def test_jobindex_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("jobindex")
    with probe_sized("jobindex", "listing"):
        postings = jobindex.scrape({"search_keywords": [KW], "location": "Copenhagen"})
    assert_zero_hits("jobindex", postings)
