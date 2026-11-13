"""Live smoke test for Flatchr's public career-site feed: Flatchr's own careers page.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import flatchr
from live_utils import assert_field_contract


@pytest.mark.live
def test_flatchr_live_returns_valid_postings():
    postings = flatchr.scrape({"flatchr_companies": ["flatchr"]})
    assert postings
    assert_field_contract("flatchr", postings, mode="collect")
