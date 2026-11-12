"""Live smoke test for Beetween: Giboire's career site on ``giboire.nous-recrutons.fr`` (open jobs, in French).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import beetween


@pytest.mark.live
def test_beetween_live_returns_valid_postings():
    postings = beetween.scrape({"beetween_companies": ["giboire"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
