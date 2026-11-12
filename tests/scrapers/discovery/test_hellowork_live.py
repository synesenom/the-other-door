"""Live smoke test for HelloWork employer discovery: one search page, logged out, one request.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers import drain_errors
from door.scrapers.discovery import hellowork


@pytest.mark.live
def test_hellowork_live_queues_on_topic_employers():
    drain_errors()
    config = {"search_keywords": ["chef de projet"], "location": "Paris"}
    result = hellowork.run(config, budget=1, rotation=["chef de projet"])
    errors = drain_errors().get("hellowork", [])
    assert result["requests"] == 1 and not result["pushback"], f"{result['stopped']}; errors: {errors}"
    assert result["employers"], f"Expected at least one employer from HelloWork; errors: {errors}"
    for emp in result["employers"]:
        assert emp["company"] and emp["titles"] and emp["links"]
        for link in emp["links"]:
            assert link.startswith("https://www.hellowork.com/fr-fr/emplois/") and "?" not in link
