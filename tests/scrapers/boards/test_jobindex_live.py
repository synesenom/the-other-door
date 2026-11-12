"""Live smoke test for Jobindex (C3, smoke layer).

Opt-in (marked `live`): hits the real site. Run with `./scripts/run-test.sh --live`.
Asserts the contract — at least one valid JobPosting with the essential fields
populated — so a silent upstream change surfaces as a failure.
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.boards import jobindex


@pytest.mark.live
def test_jobindex_returns_valid_postings():
    postings = jobindex.scrape({"role_targets": ["data scientist"], "location": "Copenhagen"})

    assert len(postings) >= 1
    for p in postings[:5]:
        JobPosting.model_validate(p)
        assert p["title"], "title should be non-empty"
        assert p["company"], "company should be non-empty"
        assert p["url"], "url should be non-empty"
