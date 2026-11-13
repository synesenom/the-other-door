"""Live smoke test for Choisir le service public (choisirleservicepublic.gouv.fr).

Opt-in (marked `live`): fetches the real search page and ads over plain HTTP. Run with
`./scripts/run-test.sh --live`. Asserts the contract: at least one valid JobPosting with the
essential fields filled in, so a silent upstream change surfaces as a failure.
"""

import pytest

from door.scrapers.boards import choisirleservicepublic
from live_utils import assert_field_contract, assert_zero_hits, drain_zero_hit_state, NONSENSE_KEYWORD as KW


@pytest.mark.live
def test_choisirleservicepublic_live_returns_valid_postings():
    config = {"search_keywords": ["chef de projet"], "topic_terms": ["chef de projet*", "chargé de projet*", "project manager*"], "location": "Paris", "max_pages_per_keyword": 1}
    postings = choisirleservicepublic.scrape(config)
    assert postings
    assert_field_contract("choisirleservicepublic", postings, config)


@pytest.mark.live
def test_choisirleservicepublic_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("choisirleservicepublic")
    postings = choisirleservicepublic.scrape({"search_keywords": [KW], "location": "Paris", "max_pages_per_keyword": 1})
    assert_zero_hits("choisirleservicepublic", postings)
