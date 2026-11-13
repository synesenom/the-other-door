"""Live smoke tests for the Signatur job portal, one per mode (#19): Helsingør Kommune's list (ClientId 2296) and two
of its ads, and a real employer's careers page still detected as Signatur.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import signatur
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_detects, assert_listing, probe_sized

_CLIENT = "2296"
CONFIG = {"signatur_companies": [_CLIENT], "location": "Copenhagen"}
NO_PAGE2 = "a customer's job list is one page with every open job"


@pytest.mark.live
def test_signatur_listing_live():
    """The list: titles and links (`locations=False`: the place is on the ad; `dates=False`: the portal gives none)."""
    assert_listing("signatur", signatur, CONFIG, locations=False, dates=False)


@pytest.mark.live
def test_signatur_details_live():
    """Two ads' pages: title, workplace address and text."""
    with probe_sized("signatur", "details"):
        session = PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0)
        company, jobs = signatur._parse_list(session.get(f"{signatur._BASE}/JobList.aspx", params={"ClientId": _CLIENT}).text)
        assert jobs, "signatur [details]: no jobs on the list"
        now = datetime.now(timezone.utc)
        postings = []
        for job in jobs[:2]:
            detail = signatur._parse_detail(session.get(signatur._detail_url(_CLIENT, job["id"])).text)
            assert detail is not None, f"signatur [details]: job {job['id']} has no ad body"
            postings.append(signatur._to_posting(job, detail, _CLIENT, company or f"Signatur {_CLIENT}", now))
    assert_contract("signatur", postings, "details", config=CONFIG, locations=True)


@pytest.mark.live
def test_signatur_detection_live():
    """A real employer's careers page still shows signatur and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("signatur")
