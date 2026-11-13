"""Live smoke test for the Talentech HR-Manager feed: Region Hovedstaden (issue #228).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import hr_manager
from live_utils import assert_field_contract


@pytest.mark.live
def test_hr_manager_live_returns_valid_postings():
    postings = hr_manager.scrape({"hr_manager_aliases": ["regionh"]})
    assert postings
    assert_field_contract("hr_manager", postings, mode="collect")
