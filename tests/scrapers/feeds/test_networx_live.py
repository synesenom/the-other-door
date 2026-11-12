"""Live smoke test for Networx's public search by client: Havant & South Downs College (client id 3509).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import networx


@pytest.mark.live
def test_networx_live_returns_valid_postings():
    postings = networx.scrape({"networx_companies": ["3509"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
