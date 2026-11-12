"""Live smoke test for Reed (reed.co.uk).

Opt-in (marked `live`): fetches the real search page and ads over plain HTTP. Run with
`./scripts/run-test.sh --live`. Asserts the contract: at least one valid JobPosting with the
essential fields filled in, so a silent upstream change surfaces as a failure.
"""

import pytest

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.boards import reed
from live_utils import skip_if_refused_in_ci


@pytest.mark.live
def test_reed_live_returns_valid_postings():
    drain_errors()
    postings = reed.scrape({"search_keywords": ["project manager"], "topic_terms": ["project*"], "location": "London",
                            "max_pages_per_keyword": 1})
    if not postings:
        skip_if_refused_in_ci("reed", drain_errors().get("reed", []))
    assert postings
    for p in postings[:5]:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
