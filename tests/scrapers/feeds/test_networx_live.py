"""Live smoke test for Networx's public search by client: Havant & South Downs College (client id 3509).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import networx
from live_utils import assert_detects, assert_field_contract


@pytest.mark.live
def test_networx_live_returns_valid_postings():
    postings = networx.scrape({"networx_companies": ["3509"]})
    assert postings
    assert_field_contract("networx", postings, mode="collect")


@pytest.mark.live
def test_networx_detection_live():
    """A real employer's careers page still shows networx and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("networx")
