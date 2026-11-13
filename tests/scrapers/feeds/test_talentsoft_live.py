"""Live smoke test for Talentsoft's public list pages and RSS feed: AGRICA (issue #559).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import talentsoft
from live_utils import assert_detects, assert_field_contract


@pytest.mark.live
def test_talentsoft_live_returns_valid_postings():
    postings = talentsoft.scrape({"talentsoft_hosts": ["agrica-career.talent-soft.com"]})
    assert postings
    assert_field_contract("talentsoft", postings, mode="collect")


@pytest.mark.live
def test_talentsoft_detection_live():
    """A real employer's careers page still shows talentsoft and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("talentsoft")
