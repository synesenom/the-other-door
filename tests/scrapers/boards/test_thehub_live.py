"""Live smoke test for The Hub (C4, smoke layer).

Opt-in (marked `live`): fetches the real Nuxt-rendered pages over plain HTTP. Run with
`./scripts/run-test.sh --live`. Asserts the contract — at least one valid JobPosting with
the essential fields populated, found by evaluating the page's `window.__NUXT__` — so a
silent upstream change surfaces as a failure.
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.boards import thehub
from live_utils import NONSENSE_KEYWORD as KW, assert_zero_hits, drain_zero_hit_state


@pytest.mark.live
def test_thehub_returns_valid_postings():
    postings = thehub.scrape({"role_targets": ["data scientist"], "location": "Copenhagen"})

    assert len(postings) >= 1
    for p in postings[:5]:
        JobPosting.model_validate(p)
        assert p["title"], "title should be non-empty"
        assert p["company"], "company should be non-empty"
        assert p["url"], "url should be non-empty"
        assert p["description"], "description should come from the job page"


@pytest.mark.live
def test_thehub_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("thehub")
    postings = thehub.scrape({"search_keywords": [KW], "location": "Copenhagen"})
    assert_zero_hits("thehub", postings)
