"""Live smoke test for Eploy's public RSS data feed: Vitality (an ``eploy.net`` host) and the Alan Turing Institute
(a custom domain).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import eploy
from live_utils import assert_detects


@pytest.mark.live
@pytest.mark.parametrize("host", ["vitalityweb.eploy.net", "portal.careers.turing.ac.uk"])
def test_eploy_live_returns_valid_postings(host):
    postings = eploy.scrape({"eploy_hosts": [host]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]


@pytest.mark.live
def test_eploy_detection_live():
    """A real employer's careers page still shows eploy and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("eploy")
