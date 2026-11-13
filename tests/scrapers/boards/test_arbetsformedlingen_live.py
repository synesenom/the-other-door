"""Live smoke test for Arbetsförmedlingen (Platsbanken, the JobSearch API). Opt-in (marked `live`): reads the real
API for one keyword in Stockholm. Asserts the contract: at least one valid JobPosting with title, company, url and
description."""

import pytest

from door.core.models import JobPosting
from door.scrapers.boards import arbetsformedlingen
from live_utils import NONSENSE_KEYWORD as KW, assert_zero_hits, drain_zero_hit_state


@pytest.mark.live
def test_arbetsformedlingen_returns_valid_postings():
    postings = arbetsformedlingen.scrape({"search_keywords": ["project manager"], "location": "Stockholm"})

    assert len(postings) >= 1
    for p in postings[:5]:
        JobPosting.model_validate(p)
        assert p["title"], "title should be non-empty"
        assert p["company"], "company should be non-empty"
        assert p["url"].startswith("https://arbetsformedlingen.se/platsbanken/"), "url should be the ad's page"
        assert p["description"], "description comes with the search answer"


@pytest.mark.live
def test_arbetsformedlingen_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("arbetsformedlingen")
    postings = arbetsformedlingen.scrape({"search_keywords": [KW], "location": "Stockholm"})
    assert_zero_hits("arbetsformedlingen", postings)
