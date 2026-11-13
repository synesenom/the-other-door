"""Live smoke test for Networx's public search by client: Havant & South Downs College (client id 3509).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import networx
from live_utils import assert_detects


@pytest.mark.live
def test_networx_live_returns_valid_postings():
    postings = networx.scrape({"networx_companies": ["3509"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]


@pytest.mark.live
def test_networx_detection_live():
    """A real employer's careers page still shows networx and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("networx")
