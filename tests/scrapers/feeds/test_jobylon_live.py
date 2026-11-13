"""Live smoke test for Jobylon's public company job widget: Lyko (company 2420).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import jobylon
from live_utils import assert_field_contract


@pytest.mark.live
def test_jobylon_live_returns_valid_postings():
    postings = jobylon.scrape({"jobylon_companies": ["2420"]})
    assert postings
    assert_field_contract("jobylon", postings, mode="collect")
