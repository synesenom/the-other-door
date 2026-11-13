"""Live smoke test for Taleez's public job list: Donecle (Toulouse).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import taleez
from live_utils import assert_detects, assert_field_contract


@pytest.mark.live
def test_taleez_live_returns_valid_postings():
    postings = taleez.scrape({"taleez_companies": ["donecle"]})
    assert postings
    assert_field_contract("taleez", postings, mode="collect")


@pytest.mark.live
def test_taleez_detection_live():
    """A real employer's careers page still shows taleez and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("taleez")
