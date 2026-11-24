"""Live check of the public-only fetch path (#548): an ordinary public site still answers through both
adapters. Opt-in (marked `live`): run with `./scripts/run-test.sh --live -k public`."""

import pytest

from door.scrapers.http_client import PoliteSession

pytestmark = pytest.mark.live


@pytest.mark.parametrize("system_trust", [False, True], ids=["certifi", "system_trust"])
def test_public_https_site_answers_through_the_public_only_adapter(system_trust):
    session = PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, system_trust=system_trust)
    assert session.get("https://example.com").status_code == 200
