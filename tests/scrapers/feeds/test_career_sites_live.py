"""Live smoke test for career sites read through sitemaps and JobPosting markup:
Publicis Sapient (issue #232).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import career_sites
from live_utils import assert_detects


@pytest.mark.live
def test_career_sites_live_returns_valid_postings(monkeypatch):
    monkeypatch.setattr(career_sites, "_MAX_PAGES", 5)
    postings = career_sites.scrape({"career_sites": ["careers.publicissapient.com"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"]


@pytest.mark.live
def test_career_sites_detection_live():
    """A real employer's careers page still shows career_sites and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("career_sites")
