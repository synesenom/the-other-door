"""Live smoke test for ReliefWeb (smoke layer). Opt-in (marked `live`): reads the real RSS feed of one keyword.
Asserts the contract: at least one valid JobPosting with title, company and url, home-based or not."""

import pytest

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.boards import reliefweb
from live_utils import not_reached_if_refused


@pytest.mark.live
def test_reliefweb_returns_valid_postings():
    drain_errors()
    postings = reliefweb.scrape({"search_keywords": ["monitoring evaluation"], "location": "Copenhagen"})

    if not postings:
        not_reached_if_refused("reliefweb", drain_errors().get("reliefweb", []))
    assert len(postings) >= 1
    for p in postings[:5]:
        JobPosting.model_validate(p)
        assert p["title"], "title should be non-empty"
        assert p["company"], "company should be non-empty"
        assert p["url"].startswith("https://reliefweb.int/job/"), "url should be the ad's page"
        assert p["description"], "description comes with the feed"
