"""Live smoke test for Personio's XML feed: PNO Group Europe (issue #558).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import personio
from live_utils import assert_field_contract


@pytest.mark.live
def test_personio_live_returns_valid_postings():
    postings = personio.scrape({"personio_companies": ["pno-group-europe"], "location": "Paris, France"})
    assert postings
    assert_field_contract("personio", postings, mode="collect")
