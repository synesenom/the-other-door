"""Live smoke test for ReachMee's public job list: Örebro universitet's Swedish publishing site.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import reachmee
from live_utils import assert_field_contract


@pytest.mark.live
def test_reachmee_live_returns_valid_postings():
    postings = reachmee.scrape({"reachmee_companies": ["I003/354/5"], "location": "Örebro, Sweden"})
    assert postings
    assert_field_contract("reachmee", postings, mode="collect")
