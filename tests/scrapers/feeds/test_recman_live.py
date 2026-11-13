"""Live smoke test for Recman: Jobconnect Sweden's career site (a few open jobs, in Swedish).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import recman
from live_utils import assert_field_contract


@pytest.mark.live
def test_recman_live_returns_valid_postings():
    postings = recman.scrape({"recman_companies": ["jobconnectsverige"]})
    assert postings
    assert_field_contract("recman", postings, mode="collect")
