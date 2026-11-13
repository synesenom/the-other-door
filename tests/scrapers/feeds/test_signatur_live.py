"""Live smoke test for the Signatur job portal: Helsingør Kommune.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import signatur
from live_utils import assert_field_contract


@pytest.mark.live
def test_signatur_live_returns_valid_postings():
    postings = signatur.scrape({"signatur_companies": ["2296"]})
    assert postings
    assert_field_contract("signatur", postings, mode="collect")
