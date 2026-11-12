"""Live smoke test for Emply's vacancy API: DanChurchAid (issue #437).

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import emply


@pytest.mark.live
def test_emply_live_returns_valid_postings():
    postings = emply.scrape({"emply_tenants": ["dca"]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]


@pytest.mark.live
def test_emply_live_reads_aarhus_universitys_embedded_list():
    """Issue #431: Aarhus University's vacancy page embeds the list; the ads carry the department and the ad text."""
    postings = emply.scrape({"emply_tenants": ["https://international.au.dk/about/profile/vacant-positions/"]})
    assert postings
    for p in postings[:5]:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] == "Aarhus University" and p["url"].startswith("https://international.au.dk/")
        assert p["description"]
