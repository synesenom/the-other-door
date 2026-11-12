"""Live smoke test for Jobbsafari employer discovery: one search page, logged out, one request.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers import drain_errors
from door.scrapers.discovery import jobbsafari
from live_utils import skip_if_refused_in_ci


@pytest.mark.live
def test_jobbsafari_live_queues_on_topic_employers():
    drain_errors()
    config = {"search_keywords": ["software engineer"], "location": "Stockholm"}
    result = jobbsafari.run(config, budget=1, rotation=["software engineer"])
    errors = drain_errors().get("jobbsafari", [])
    if result["pushback"]:
        skip_if_refused_in_ci("jobbsafari", errors or [result["stopped"]])
    assert result["requests"] == 1 and not result["pushback"], f"{result['stopped']}; errors: {errors}"
    assert result["employers"], f"Expected at least one employer from Jobbsafari; errors: {errors}"
    for emp in result["employers"]:
        assert emp["company"] and emp["titles"]
        for link in emp["links"]:
            assert link.startswith("http") and "utm_" not in link
