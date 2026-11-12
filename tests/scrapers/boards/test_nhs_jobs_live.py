"""Live smoke test for NHS Jobs (jobs.nhs.uk).

Opt-in (marked `live`): fetches the real search page and ads over plain HTTP. Run with
`./scripts/run-test.sh --live`. Asserts the contract: at least one valid JobPosting with the
essential fields filled in, so a silent upstream change surfaces as a failure.
"""

import pytest

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.boards import nhs_jobs
from live_utils import skip_if_refused_in_ci


@pytest.mark.live
def test_nhs_jobs_live_returns_valid_postings():
    drain_errors()
    # NHS search is loose (a "project manager" page can be all nurses and doctors), so search for what
    # NHS Jobs always lists in London: one page of nurses is never empty, on-topic or not.
    postings = nhs_jobs.scrape({"search_keywords": ["nurse"], "topic_terms": ["nurse*"],
                                "location": "London", "max_pages_per_keyword": 1})
    if not postings:
        skip_if_refused_in_ci("nhs_jobs", drain_errors().get("nhs_jobs", []))
    assert postings
    for p in postings[:5]:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
