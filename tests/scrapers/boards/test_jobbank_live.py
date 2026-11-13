"""Live smoke test for Akademikernes Jobbank (jobbank.dk).

Opt-in (marked `live`): fetches the real search page and ads over plain HTTP. Run with
`./scripts/run-test.sh --live`. Asserts the contract: at least one valid JobPosting with the
essential fields filled in, so a silent upstream change surfaces as a failure.
"""

import pytest

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.boards import jobbank
from live_utils import not_reached_if_refused


@pytest.mark.live
def test_jobbank_live_returns_valid_postings():
    drain_errors()
    postings = jobbank.scrape({"search_keywords": ["analyst"], "location": "Copenhagen", "max_pages_per_keyword": 1})
    if not postings:
        not_reached_if_refused("jobbank", drain_errors().get("jobbank", []))
    assert postings
    for p in postings[:5]:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
