"""Live smoke test for Taleez's public job list: Donecle (Toulouse).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import taleez
from live_utils import assert_field_contract


@pytest.mark.live
def test_taleez_live_returns_valid_postings():
    postings = taleez.scrape({"taleez_companies": ["donecle"]})
    assert postings
    assert_field_contract("taleez", postings, mode="collect")
