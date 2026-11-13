"""Live smoke test for jobs.ac.uk (academic jobs).

Opt-in (marked `live`): fetches the real search page and ads over plain HTTP. Run with
`./scripts/run-test.sh --live`. Asserts the contract: at least one valid JobPosting with the
essential fields filled in, so a silent upstream change surfaces as a failure.
"""

import pytest

from door.scrapers import drain_errors
from door.scrapers.boards import jobs_ac_uk
from live_utils import assert_field_contract, assert_zero_hits, drain_zero_hit_state, NONSENSE_KEYWORD as KW, not_reached_if_refused


@pytest.mark.live
def test_jobs_ac_uk_live_returns_valid_postings():
    drain_errors()
    config = {"search_keywords": ["research associate"], "topic_terms": ["research*", "postdoc*"], "location": "London", "max_pages_per_keyword": 1}
    postings = jobs_ac_uk.scrape(config)
    if not postings:
        not_reached_if_refused("jobs_ac_uk", drain_errors().get("jobs_ac_uk", []))
    assert postings
    assert_field_contract("jobs_ac_uk", postings, config)


@pytest.mark.live
def test_jobs_ac_uk_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("jobs_ac_uk")
    postings = jobs_ac_uk.scrape({"search_keywords": [KW], "location": "London", "max_pages_per_keyword": 1})
    assert_zero_hits("jobs_ac_uk", postings)
