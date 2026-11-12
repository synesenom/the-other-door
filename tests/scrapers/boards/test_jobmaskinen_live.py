"""Live smoke test for Jobmaskinen (job.jobmaskinen.dk). Opt-in (marked `live`)."""

import pytest

from door.core.models import JobPosting
from door.scrapers.boards import jobmaskinen


@pytest.mark.live
def test_jobmaskinen_returns_valid_postings():
    postings = jobmaskinen.scrape({"search_keywords": ["elektriker"], "location": "Copenhagen"})

    assert len(postings) >= 1
    for p in postings[:5]:
        JobPosting.model_validate(p)
        assert p["title"], "title should be non-empty"
        assert p["company"], "company should be non-empty"
        assert p["url"], "url should be non-empty"
        assert p["description"], "description should be non-empty"
