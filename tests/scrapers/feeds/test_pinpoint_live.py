"""Live smoke test for Pinpoint's public career-site feed: Factbird.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import pinpoint
from live_utils import assert_field_contract


@pytest.mark.live
def test_pinpoint_live_returns_valid_postings():
    postings = pinpoint.scrape({"pinpoint_companies": ["factbird"]})
    assert postings
    assert_field_contract("pinpoint", postings, mode="collect")
