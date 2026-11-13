"""Live smoke test for KÖZSZOLGÁLLÁS (kozszolgallas.ksz.gov.hu, the Hungarian public-service job portal).

Opt-in (marked `live`): fetches the real search and ad pages over plain HTTP. Run with
`./scripts/run-test.sh --live`. Asserts the contract: at least one valid JobPosting with the
essential fields filled in, so a silent upstream change surfaces as a failure.
"""

import pytest

from door.scrapers.boards import kozigallas
from live_utils import assert_field_contract, assert_zero_hits, drain_zero_hit_state, NONSENSE_KEYWORD as KW


@pytest.mark.live
def test_kozigallas_live_returns_valid_postings():
    config = {"search_keywords": ["ápoló"], "topic_terms": ["*ápoló*", "*ápolói*"], "location": "Budapest", "max_pages_per_keyword": 1}
    postings = kozigallas.scrape(config)
    assert postings
    assert_field_contract("kozigallas", postings, config)


@pytest.mark.live
def test_kozigallas_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("kozigallas")
    postings = kozigallas.scrape({"search_keywords": [KW], "location": "Budapest", "max_pages_per_keyword": 1})
    assert_zero_hits("kozigallas", postings)
