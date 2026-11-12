"""Live smoke test for Talentsoft's public list pages and RSS feed: AGRICA (issue #559).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import talentsoft


@pytest.mark.live
def test_talentsoft_live_returns_valid_postings():
    postings = talentsoft.scrape({"talentsoft_hosts": ["agrica-career.talent-soft.com"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]
