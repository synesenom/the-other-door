"""Live smoke test for Taleez's public job list: Donecle (Toulouse).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import taleez


@pytest.mark.live
def test_taleez_live_returns_valid_postings():
    postings = taleez.scrape({"taleez_companies": ["donecle"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
