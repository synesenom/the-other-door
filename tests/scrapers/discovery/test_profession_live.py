"""Live smoke test for profession.hu employer discovery (#19): one paced search page, logged out, one request.

It still yields employers with a name, a title and, where it gives one, a link; a refusal (a 403 or 429, a login
page, a captcha or consent page instead of the results) is not reached, never "no employers".
Run locally, not in CI (`./scripts/run-test.sh --live tests/scrapers/discovery`).
"""

import pytest

from door.scrapers import drain_errors
from door.scrapers.discovery import profession
from live_utils import assert_discovery, fail

KEYWORD = "software engineer"


@pytest.mark.live
def test_profession_employers_live():
    drain_errors()
    config = {"search_keywords": [KEYWORD], "location": "Budapest"}
    result = profession.run(config, budget=1, rotation=[KEYWORD])
    errors = drain_errors().get("profession", [])
    assert_discovery("profession", result, errors, link_prefix="https://www.profession.hu/allas")
    assert result["requests"] == 1, fail("profession", "employers", f"{result['requests']} requests, not one")
    for emp in result["employers"]:
        assert all("?" not in link for link in emp["links"]), fail("profession", "employers", f"a link with its query: {emp['links']}")
