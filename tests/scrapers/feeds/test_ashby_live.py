"""Live smoke test for the Ashby job-board API: Pleo (issue #230).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import ashby
from live_utils import assert_field_contract


@pytest.mark.live
def test_ashby_live_returns_valid_postings():
    postings = ashby.scrape({"ashby_companies": ["pleo"]})
    assert postings
    assert_field_contract("ashby", postings, mode="collect")
