"""Live smoke test for Reed (reed.co.uk).

Opt-in (marked `live`): fetches the real search page and ads over plain HTTP. Run with
`./scripts/run-test.sh --live`. Asserts the contract: at least one valid JobPosting with the
essential fields filled in, so a silent upstream change surfaces as a failure.
"""

import pytest

from door.scrapers import drain_errors
from door.scrapers.boards import reed
from live_utils import assert_field_contract, assert_zero_hits, drain_zero_hit_state, NONSENSE_KEYWORD as KW, not_reached_if_refused


@pytest.mark.live
def test_reed_live_returns_valid_postings():
    drain_errors()
    config = {"search_keywords": ["project manager"], "topic_terms": ["project*"], "location": "London", "max_pages_per_keyword": 1}
    postings = reed.scrape(config)
    if not postings:
        not_reached_if_refused("reed", drain_errors().get("reed", []))
    assert postings
    assert_field_contract("reed", postings, config)


@pytest.mark.live
def test_reed_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("reed")
    postings = reed.scrape({"search_keywords": [KW], "location": "London", "max_pages_per_keyword": 1})
    assert_zero_hits("reed", postings)
