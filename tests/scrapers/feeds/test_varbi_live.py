"""Live smoke test for Varbi's public RSS feed and job list: Karolinska Institutet (issue #525).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import varbi
from live_utils import assert_detects, assert_field_contract


@pytest.mark.live
def test_varbi_live_returns_valid_postings():
    postings = varbi.scrape({"varbi_tenants": ["ki"]})
    assert postings
    assert_field_contract("varbi", postings, mode="collect")


@pytest.mark.live
def test_varbi_detection_live():
    """A real employer's careers page still shows varbi and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("varbi")
