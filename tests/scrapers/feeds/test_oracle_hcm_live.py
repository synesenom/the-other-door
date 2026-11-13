"""Live smoke test for Oracle Cloud HCM's public candidate-experience feed: Danske Bank's career site.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers.feeds import oracle_hcm
from live_utils import assert_field_contract


@pytest.mark.live
def test_oracle_hcm_live_returns_valid_postings(monkeypatch):
    monkeypatch.setattr(oracle_hcm, "_PAGE", 5)
    monkeypatch.setattr(oracle_hcm, "_MAX_POSTINGS", 5)  # a smoke test reads one small page
    postings = oracle_hcm.scrape({"oracle_hcm_companies": ["ejqi.fa.ocs.oraclecloud.eu/CX_1001"]})
    assert postings
    assert_field_contract("oracle_hcm", postings, mode="collect")
