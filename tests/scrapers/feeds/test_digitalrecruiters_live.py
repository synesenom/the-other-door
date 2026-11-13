"""Live smoke test for Digitalrecruiters career sites: Franprix's, a small tenant (issue #561).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import digitalrecruiters
from live_utils import assert_detects, assert_field_contract


@pytest.mark.live
def test_digitalrecruiters_live_returns_valid_postings(monkeypatch):
    monkeypatch.setattr(digitalrecruiters, "_MAX_PAGES", 3)   # the tenant's Crawl-delay is 10 s a page
    postings = digitalrecruiters.scrape({"digitalrecruiters_sites": ["recrutement.franprix.fr"], "location": "Paris"})
    assert postings
    assert_field_contract("digitalrecruiters", postings, mode="collect")


@pytest.mark.live
def test_digitalrecruiters_detection_live():
    """A real employer's careers page still shows digitalrecruiters and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("digitalrecruiters")
