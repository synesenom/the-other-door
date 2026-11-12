"""Live smoke test for the SmartRecruiters postings API: Inter IKEA Group.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import smartrecruiters


@pytest.mark.live
def test_smartrecruiters_live_returns_valid_postings():
    result = smartrecruiters.probe({"smartrecruiters_companies": ["interikeagroup"]})
    assert result and result["postings"]
    for p in result["postings"]:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"]
