"""Live smoke test for Jobindex (C3, smoke layer).

Opt-in (marked `live`): hits the real site. Run with `./scripts/run-test.sh --live`.
Asserts the contract — at least one valid JobPosting with the essential fields
populated — so a silent upstream change surfaces as a failure.
"""

import pytest

from door.scrapers.boards import jobindex
from live_utils import assert_field_contract, assert_zero_hits, drain_zero_hit_state, NONSENSE_KEYWORD as KW


@pytest.mark.live
def test_jobindex_returns_valid_postings():
    config = {"role_targets": ["data scientist"], "location": "Copenhagen"}
    postings = jobindex.scrape(config)

    assert len(postings) >= 1
    assert_field_contract("jobindex", postings, config)


@pytest.mark.live
def test_jobindex_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("jobindex")
    postings = jobindex.scrape({"search_keywords": [KW], "location": "Copenhagen"})
    assert_zero_hits("jobindex", postings)
