"""Live smoke test for KÖZSZOLGÁLLÁS (kozszolgallas.ksz.gov.hu, the Hungarian public-service job portal).

Opt-in (marked `live`): fetches the real search and ad pages over plain HTTP. Run with
`./scripts/run-test.sh --live`. Asserts the contract: at least one valid JobPosting with the
essential fields filled in, so a silent upstream change surfaces as a failure.
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.boards import kozigallas


@pytest.mark.live
def test_kozigallas_live_returns_valid_postings():
    postings = kozigallas.scrape(
        {"search_keywords": ["ápoló"], "topic_terms": ["*ápoló*", "*ápolói*"],
         "location": "Budapest", "max_pages_per_keyword": 1})
    assert postings
    for p in postings[:5]:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
