"""Live smoke test for ReachMee's public job list: Örebro universitet's Swedish publishing site.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import reachmee
from live_utils import assert_detects


@pytest.mark.live
def test_reachmee_live_returns_valid_postings():
    postings = reachmee.scrape({"reachmee_companies": ["I003/354/5"], "location": "Örebro, Sweden"})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]


@pytest.mark.live
def test_reachmee_detection_live():
    """A real employer's careers page still shows reachmee and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("reachmee")
