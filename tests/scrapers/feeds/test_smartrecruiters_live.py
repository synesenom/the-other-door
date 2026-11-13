"""Live smoke test for the SmartRecruiters postings API: Inter IKEA Group.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import smartrecruiters
from live_utils import assert_detects


@pytest.mark.live
def test_smartrecruiters_live_returns_valid_postings():
    result = smartrecruiters.probe({"smartrecruiters_companies": ["interikeagroup"]})
    assert result and result["postings"]
    for p in result["postings"]:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"]


@pytest.mark.live
def test_smartrecruiters_detection_live():
    """A real employer's careers page still shows smartrecruiters and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("smartrecruiters")
