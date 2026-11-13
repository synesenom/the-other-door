"""Live smoke test for ReliefWeb (smoke layer). Opt-in (marked `live`): reads the real RSS feed of one keyword.
Asserts the contract: at least one valid JobPosting with title, company and url, home-based or not."""

import pytest

from door.scrapers import drain_errors
from door.scrapers.boards import reliefweb
from live_utils import assert_field_contract, assert_zero_hits, drain_zero_hit_state, NONSENSE_KEYWORD as KW, not_reached_if_refused


@pytest.mark.live
def test_reliefweb_returns_valid_postings():
    drain_errors()
    config = {"search_keywords": ["monitoring evaluation"], "location": "Copenhagen"}
    postings = reliefweb.scrape(config)

    if not postings:
        not_reached_if_refused("reliefweb", drain_errors().get("reliefweb", []))
    assert len(postings) >= 1
    assert_field_contract("reliefweb", postings, config)
    assert all(p["url"].startswith("https://reliefweb.int/job/") for p in postings)


@pytest.mark.live
def test_reliefweb_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19)."""
    drain_zero_hit_state("reliefweb")
    postings = reliefweb.scrape({"search_keywords": [KW], "location": "Copenhagen"})
    assert_zero_hits("reliefweb", postings)
