"""Live smoke test for the Recruitee careers API: Famly (issue #231).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import recruitee
from live_utils import assert_field_contract


@pytest.mark.live
def test_recruitee_live_returns_valid_postings():
    postings = recruitee.scrape({"recruitee_companies": ["famly"]})
    assert postings
    assert_field_contract("recruitee", postings, mode="collect")
