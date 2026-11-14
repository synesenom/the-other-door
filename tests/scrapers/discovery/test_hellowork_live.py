"""Live smoke test for HelloWork employer discovery (#19): one paced search page, logged out, one request.

It still yields employers with a name, a title and, where it gives one, a link; a refusal (a 403 or 429, a login
page, a captcha or consent page instead of the results) is not reached, never "no employers".
Run locally, not in CI (`./scripts/run-test.sh --live tests/scrapers/discovery`).
"""

import pytest

from door.scrapers import drain_errors
from door.scrapers.discovery import hellowork
from live_utils import assert_discovery, fail

KEYWORD = "chef de projet"


@pytest.mark.live
def test_hellowork_employers_live():
    drain_errors()
    config = {"search_keywords": [KEYWORD], "location": "Paris"}
    result = hellowork.run(config, budget=1, rotation=[KEYWORD])
    errors = drain_errors().get("hellowork", [])
    assert_discovery("hellowork", result, errors, link_prefix="https://www.hellowork.com/fr-fr/emplois/")
    assert result["requests"] == 1, fail("hellowork", "employers", f"{result['requests']} requests, not one")
    for emp in result["employers"]:
        assert all("?" not in link for link in emp["links"]), fail("hellowork", "employers", f"a link with its query: {emp['links']}")
