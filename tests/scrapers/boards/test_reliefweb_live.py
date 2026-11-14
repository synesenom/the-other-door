"""Live smoke tests for ReliefWeb (reliefweb.int, the UN OCHA job board), one per mode (#19): the RSS feed of
"monitoring evaluation" and the zero-hit answer.

Opt-in (marked `live`): hits the real feed. Run with `./scripts/run-test.sh --live`.
"""

import pytest

from door.scrapers.boards import reliefweb
from live_utils import NONSENSE_KEYWORD as KW, assert_listing, assert_zero_hits, drain_zero_hit_state, probe_sized

CONFIG = {"search_keywords": ["monitoring evaluation"], "location": "Copenhagen"}
NO_PAGE2 = "the RSS feed has no paging (`page` and `offset` are ignored): one answer is a keyword's newest 20 jobs"
NO_DETAILS = "each feed item carries the whole ad in its description"


@pytest.mark.live
def test_reliefweb_listing_live():
    """Every field, the description too, comes with the feed (worldwide: no local rule)."""
    assert_listing("reliefweb", reliefweb, CONFIG, descriptions=True)


@pytest.mark.live
def test_reliefweb_zero_hits_live():
    """A keyword no ad contains comes back as a recognised page with no hits: a quiet day, not a changed site (#19).
    An empty 202 answer (the load balancer's challenge) is asked for once more, hence two requests."""
    drain_zero_hit_state("reliefweb")
    with probe_sized("reliefweb", "listing", most=2):
        postings = reliefweb.scrape({"search_keywords": [KW], "location": "Copenhagen"})
    assert_zero_hits("reliefweb", postings)
