"""Live smoke tests for Varbi's public RSS feed and board page, one per mode (#19): Karolinska Institutet (``ki``),
and a real employer's careers page still detected as Varbi.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers import drain_errors
from door.scrapers.feeds import varbi
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_detects, assert_listing, not_reached_if_refused, probe_sized

CONFIG = {"varbi_tenants": ["ki"], "location": "Stockholm"}
NO_PAGE2 = "one RSS answer lists every open ad of a tenant"


@pytest.mark.live
def test_varbi_listing_live():
    """The RSS feed: title, date and whole text (`locations=False`: the feed has no place; the board page gives it)."""
    assert_listing("varbi", varbi, CONFIG, descriptions=True, locations=False)


@pytest.mark.live
def test_varbi_details_live():
    """The feed joined with the board page by job id, as the scraper reads a tenant: every ad gets its town."""
    drain_errors("varbi")
    with probe_sized("varbi", "details", most=2):
        session = PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0)
        postings = varbi._tenant_postings(session, "ki", datetime.now(timezone.utc))
    errors = drain_errors("varbi").get("varbi", [])
    not_reached_if_refused("varbi", errors)
    assert not errors, f"varbi [details]: the board page failed: {errors[:3]}"
    assert_contract("varbi", postings, "details", config=CONFIG, locations=True)


@pytest.mark.live
def test_varbi_detection_live():
    """A real employer's careers page still shows varbi and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("varbi")
