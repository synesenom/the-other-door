"""Live smoke test for Jobbsafari employer discovery (#19): one paced search page, logged out, one request.

It still yields employers with a name, a title and, where it gives one, a link; a refusal (a 403 or 429, a login
page, a captcha or consent page instead of the results) is not reached, never "no employers". Each link is the employer's own apply link, without its tracking query.
Run locally, not in CI (`./scripts/run-test.sh --live tests/scrapers/discovery`).
"""

import pytest

from door.scrapers import drain_errors
from door.scrapers.discovery import jobbsafari
from live_utils import assert_discovery, fail

KEYWORD = "software engineer"


@pytest.mark.live
def test_jobbsafari_employers_live():
    drain_errors()
    config = {"search_keywords": [KEYWORD], "location": "Stockholm"}
    result = jobbsafari.run(config, budget=1, rotation=[KEYWORD])
    errors = drain_errors().get("jobbsafari", [])
    assert_discovery("jobbsafari", result, errors, link_prefix="http")
    assert result["requests"] == 1, fail("jobbsafari", "employers", f"{result['requests']} requests, not one")
    for emp in result["employers"]:
        assert all("utm_" not in link for link in emp["links"]), fail("jobbsafari", "employers", f"a tracking query: {emp['links']}")
