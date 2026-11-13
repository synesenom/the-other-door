"""Live smoke test for Jobmaskinen (job.jobmaskinen.dk). Opt-in (marked `live`)."""

import pytest

from door.scrapers.boards import jobmaskinen
from live_utils import assert_field_contract, assert_zero_hits, drain_zero_hit_state, NONSENSE_KEYWORD as KW


@pytest.mark.live
def test_jobmaskinen_returns_valid_postings():
    config = {"search_keywords": ["elektriker"], "location": "Copenhagen"}
    postings = jobmaskinen.scrape(config)

    assert len(postings) >= 1
    assert_field_contract("jobmaskinen", postings, config)


@pytest.mark.live
def test_jobmaskinen_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("jobmaskinen")
    postings = jobmaskinen.scrape({"search_keywords": [KW], "location": "Copenhagen"})
    assert_zero_hits("jobmaskinen", postings)
