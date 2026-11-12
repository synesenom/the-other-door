"""Live smoke test for Varbi's public RSS feed and job list: Karolinska Institutet (issue #525).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import varbi


@pytest.mark.live
def test_varbi_live_returns_valid_postings():
    postings = varbi.scrape({"varbi_tenants": ["ki"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
