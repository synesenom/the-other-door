"""Live smoke test for the Talentech HR-Manager feed: Region Hovedstaden (issue #228).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import hr_manager
from live_utils import assert_detects


@pytest.mark.live
def test_hr_manager_live_returns_valid_postings():
    postings = hr_manager.scrape({"hr_manager_aliases": ["regionh"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"]
    # A position posted without an ad has no description; nearly all have one.
    assert sum(bool(p["description"]) for p in postings) >= 0.9 * len(postings)


@pytest.mark.live
def test_hr_manager_detection_live():
    """A real employer's careers page still shows hr_manager and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("hr_manager")
