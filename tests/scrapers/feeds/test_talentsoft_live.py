"""Live smoke test for Talentsoft's public list pages and RSS feed: AGRICA (issue #559).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import talentsoft
from live_utils import assert_detects


@pytest.mark.live
def test_talentsoft_live_returns_valid_postings():
    postings = talentsoft.scrape({"talentsoft_hosts": ["agrica-career.talent-soft.com"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]


@pytest.mark.live
def test_talentsoft_detection_live():
    """A real employer's careers page still shows talentsoft and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("talentsoft")
