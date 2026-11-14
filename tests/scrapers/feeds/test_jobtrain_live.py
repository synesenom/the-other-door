"""Live smoke test for Jobtrain's public job lists: Leigh Academies Trust (a tenant on the shared host) and
Crisis (a tenant on its own host, jobs.crisis.org.uk).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import jobtrain
from live_utils import assert_detects, assert_field_contract


@pytest.mark.live
@pytest.mark.parametrize("entry", ["leighacademiestrust", "jobs.crisis.org.uk"])
def test_jobtrain_live_returns_valid_postings(entry):
    postings = jobtrain.scrape({"jobtrain_companies": [entry]})
    assert postings
    assert_field_contract("jobtrain", postings, mode="collect")


@pytest.mark.live
def test_jobtrain_detection_live():
    """A real employer's careers page still shows jobtrain and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("jobtrain")
