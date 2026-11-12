"""Live smoke test for Globalnyt (smoke layer). Opt-in (marked `live`): reads the real ad list and the first ad pages."""

import pytest

from door.core.models import JobPosting
from door.scrapers.boards import globalnyt


@pytest.mark.live
def test_globalnyt_returns_valid_postings():
    postings = globalnyt.scrape({"search_keywords": ["rådgiver"], "location": "Copenhagen"})

    assert len(postings) >= 1
    for p in postings[:5]:
        JobPosting.model_validate(p)
        assert p["title"], "title should be non-empty"
        assert p["company"], "company should be non-empty"
        assert p["url"].startswith("https://globalnyt.dk/stilling/"), "url should be the ad's page"
    assert any(p["company"] != "Globalnyt" for p in postings), "the employer should come from the ad page"
