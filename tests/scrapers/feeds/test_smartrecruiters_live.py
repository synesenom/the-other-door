"""Live smoke test for the SmartRecruiters postings API: Inter IKEA Group.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import smartrecruiters
from live_utils import assert_field_contract


@pytest.mark.live
def test_smartrecruiters_live_returns_valid_postings():
    result = smartrecruiters.probe({"smartrecruiters_companies": ["interikeagroup"]})
    assert result and result["postings"]
    assert_field_contract("smartrecruiters", result["postings"], mode="collect")
