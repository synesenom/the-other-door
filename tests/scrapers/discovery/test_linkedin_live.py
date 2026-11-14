"""Live smoke test for LinkedIn employer discovery (#19): one paced search page, logged out, one request.

It still yields employers with a name, a title and, where it gives one, a link; a refusal (a 403 or 429, a login
page, a captcha or consent page instead of the results) is not reached, never "no employers". The logged-out guest API; an employer may have no link (Easy Apply), each has the job ids its titles came from.
Run locally, not in CI (`./scripts/run-test.sh --live tests/scrapers/discovery`).
"""

import pytest

from door.scrapers import drain_errors
from door.scrapers.discovery import linkedin
from live_utils import assert_discovery, fail

KEYWORD = "software engineer"


@pytest.mark.live
def test_linkedin_employers_live():
    drain_errors()
    config = {"search_keywords": [KEYWORD], "location": "Copenhagen"}
    result = linkedin.run(config, budget=1, pause=(0.0, 0.0), mode="rotate", rotation=[KEYWORD])
    errors = drain_errors().get("linkedin", [])
    assert_discovery("linkedin", result, errors, link_prefix="http")
    assert result["requests"] == 1, fail("linkedin", "employers", f"{result['requests']} requests, not one")
    for emp in result["employers"]:
        assert emp["job_ids"], fail("linkedin", "employers", f"{emp['company']}: no job ids")
