"""Live smoke test for Arbetsförmedlingen (Platsbanken, the JobSearch API). Opt-in (marked `live`): reads the real
API for one keyword in Stockholm. Asserts the contract: at least one valid JobPosting with title, company, url and
description."""

import pytest

from door.scrapers.boards import arbetsformedlingen
from live_utils import assert_field_contract, assert_zero_hits, drain_zero_hit_state, NONSENSE_KEYWORD as KW


@pytest.mark.live
def test_arbetsformedlingen_returns_valid_postings():
    config = {"search_keywords": ["project manager"], "location": "Stockholm"}
    postings = arbetsformedlingen.scrape(config)

    assert len(postings) >= 1
    assert_field_contract("arbetsformedlingen", postings, config)
    assert all(p["url"].startswith("https://arbetsformedlingen.se/platsbanken/") for p in postings)


@pytest.mark.live
def test_arbetsformedlingen_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("arbetsformedlingen")
    postings = arbetsformedlingen.scrape({"search_keywords": [KW], "location": "Stockholm"})
    assert_zero_hits("arbetsformedlingen", postings)
