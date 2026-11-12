"""Live smoke test for LinkedIn employer discovery: one search page of the logged-out guest API, one request.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers import drain_errors
from door.scrapers.discovery import linkedin


@pytest.mark.live
def test_linkedin_live_queues_on_topic_employers():
    drain_errors()
    config = {"search_keywords": ["software engineer"], "location": "Copenhagen"}
    result = linkedin.run(config, budget=1, pause=(0.0, 0.0), mode="rotate", rotation=["software engineer"])
    errors = drain_errors().get("linkedin", [])
    assert result["requests"] == 1 and not result["pushback"], f"{result['stopped']}; errors: {errors}"
    assert result["employers"], f"Expected at least one employer from LinkedIn; errors: {errors}"
    for emp in result["employers"]:
        assert emp["company"] and emp["titles"] and emp["job_ids"]
