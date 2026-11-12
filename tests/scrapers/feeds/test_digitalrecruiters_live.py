"""Live smoke test for Digitalrecruiters career sites: Franprix's, a small tenant (issue #561).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import digitalrecruiters


@pytest.mark.live
def test_digitalrecruiters_live_returns_valid_postings(monkeypatch):
    monkeypatch.setattr(digitalrecruiters, "_MAX_PAGES", 3)   # the tenant's Crawl-delay is 10 s a page
    postings = digitalrecruiters.scrape({"digitalrecruiters_sites": ["recrutement.franprix.fr"], "location": "Paris"})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
