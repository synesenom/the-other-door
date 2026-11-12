"""Live smoke test for Jobylon's public company job widget: Lyko (company 2420).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import jobylon


@pytest.mark.live
def test_jobylon_live_returns_valid_postings():
    postings = jobylon.scrape({"jobylon_companies": ["2420"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
