"""Live smoke test for France Travail (candidat.francetravail.fr).

Opt-in (marked `live`): fetches the real search page and ads over plain HTTP. Run with
`./scripts/run-test.sh --live`. Asserts the contract: at least one valid JobPosting with the
essential fields filled in, so a silent upstream change surfaces as a failure.
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.boards import francetravail


@pytest.mark.live
def test_francetravail_live_returns_valid_postings():
    postings = francetravail.scrape({"search_keywords": ["chef de projet"], "location": "Paris", "max_pages_per_keyword": 1})
    assert postings
    for p in postings[:5]:
        JobPosting.model_validate(p)
        assert p["title"] and p["url"] and p["description"]
    # An ad may hide its employer (a recruiter's anonymous ad); most name it.
    assert any(p["company"] for p in postings)
