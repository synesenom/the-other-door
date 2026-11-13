"""Live smoke test for Eploy's public RSS data feed: Vitality (an ``eploy.net`` host) and the Alan Turing Institute
(a custom domain).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import eploy
from live_utils import assert_field_contract


@pytest.mark.live
@pytest.mark.parametrize("host", ["vitalityweb.eploy.net", "portal.careers.turing.ac.uk"])
def test_eploy_live_returns_valid_postings(host):
    postings = eploy.scrape({"eploy_hosts": [host]})
    assert postings
    assert_field_contract("eploy", postings, mode="collect")
