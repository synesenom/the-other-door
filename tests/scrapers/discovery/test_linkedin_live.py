"""Live smoke test for LinkedIn employer discovery (#19): one paced search page, logged out, one request.

It still yields employers with a name, a title and, where it gives one, a link; a refusal (a 403 or 429, a login
page, a captcha or consent page instead of the results) is not reached, never "no employers". So is an empty
answer: "software engineer" in Copenhagen always has results, and LinkedIn answers a guest it holds back with the
same empty page as a search with none. A page of items with no card read stops the search: a change. The logged-out guest API; an employer may have no link (Easy Apply), each has the job ids its titles came from.
Run locally, not in CI (`./scripts/run-test.sh --live tests/scrapers/discovery`).
"""

import pytest

from door.scrapers import drain_errors
from door.scrapers.discovery import linkedin
from live_utils import assert_discovery, fail, not_reached

KEYWORD = "software engineer"


@pytest.mark.live
def test_linkedin_employers_live():
    drain_errors()
    config = {"search_keywords": [KEYWORD], "location": "Copenhagen"}
    result = linkedin.run(config, budget=1, pause=(0.0, 0.0), mode="rotate", rotation=[KEYWORD])
    errors = drain_errors().get("linkedin", [])
    if not result["employers"] and not result["stopped"]:
        not_reached("linkedin", "an empty answer to a search that always has results")
    assert_discovery("linkedin", result, errors, link_prefix="http")
    assert result["requests"] == 1, fail("linkedin", "employers", f"{result['requests']} requests, not one")
    for emp in result["employers"]:
        assert emp["job_ids"], fail("linkedin", "employers", f"{emp['company']}: no job ids")
