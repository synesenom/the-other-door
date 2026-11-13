"""Live smoke test for Oracle Cloud HCM's public candidate-experience feed: Danske Bank's career site.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import oracle_hcm
from live_utils import assert_detects


@pytest.mark.live
def test_oracle_hcm_live_returns_valid_postings(monkeypatch):
    monkeypatch.setattr(oracle_hcm, "_PAGE", 5)
    monkeypatch.setattr(oracle_hcm, "_MAX_POSTINGS", 5)  # a smoke test reads one small page
    postings = oracle_hcm.scrape({"oracle_hcm_companies": ["ejqi.fa.ocs.oraclecloud.eu/CX_1001"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]


@pytest.mark.live
def test_oracle_hcm_detection_live():
    """A real employer's careers page still shows oracle_hcm and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("oracle_hcm")
