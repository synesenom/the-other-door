"""Live smoke test for Jobtrain's public job lists: Leigh Academies Trust (a tenant on the shared host) and
Crisis (a tenant on its own host, jobs.crisis.org.uk).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import jobtrain


@pytest.mark.live
@pytest.mark.parametrize("entry", ["leighacademiestrust", "jobs.crisis.org.uk"])
def test_jobtrain_live_returns_valid_postings(entry):
    postings = jobtrain.scrape({"jobtrain_companies": [entry]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
