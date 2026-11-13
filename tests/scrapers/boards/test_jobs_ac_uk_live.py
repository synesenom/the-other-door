"""Live smoke test for jobs.ac.uk (academic jobs).

Opt-in (marked `live`): fetches the real search page and ads over plain HTTP. Run with
`./scripts/run-test.sh --live`. Asserts the contract: at least one valid JobPosting with the
essential fields filled in, so a silent upstream change surfaces as a failure.
"""

import pytest

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.boards import jobs_ac_uk
from live_utils import NONSENSE_KEYWORD as KW, assert_zero_hits, drain_zero_hit_state, not_reached_if_refused


@pytest.mark.live
def test_jobs_ac_uk_live_returns_valid_postings():
    drain_errors()
    postings = jobs_ac_uk.scrape({"search_keywords": ["research associate"], "topic_terms": ["research*", "postdoc*"],
                                  "location": "London", "max_pages_per_keyword": 1})
    if not postings:
        not_reached_if_refused("jobs_ac_uk", drain_errors().get("jobs_ac_uk", []))
    assert postings
    for p in postings[:5]:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]


@pytest.mark.live
def test_jobs_ac_uk_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("jobs_ac_uk")
    postings = jobs_ac_uk.scrape({"search_keywords": [KW], "location": "London", "max_pages_per_keyword": 1})
    assert_zero_hits("jobs_ac_uk", postings)
