"""Live smoke test for profession.hu employer discovery: one search page, logged out, one request.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

import pytest

from door.scrapers import drain_errors
from door.scrapers.discovery import profession


@pytest.mark.live
def test_profession_live_queues_on_topic_employers():
    drain_errors()
    config = {"search_keywords": ["software engineer"], "location": "Budapest"}
    result = profession.run(config, budget=1, rotation=["software engineer"])
    errors = drain_errors().get("profession", [])
    assert result["requests"] == 1 and not result["pushback"], f"{result['stopped']}; errors: {errors}"
    assert result["employers"], f"Expected at least one employer from profession.hu; errors: {errors}"
    for emp in result["employers"]:
        assert emp["company"] and emp["titles"] and emp["links"]
        for link in emp["links"]:
            assert link.startswith("https://www.profession.hu/allas") and "?" not in link
