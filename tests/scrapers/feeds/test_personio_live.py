"""Live smoke test for Personio's XML feed: PNO Group Europe (issue #558).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import personio


@pytest.mark.live
def test_personio_live_returns_valid_postings():
    postings = personio.scrape({"personio_companies": ["pno-group-europe"], "location": "Paris, France"})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
