"""Live smoke tests for ReachMee's public job lists, one per mode (#19): Örebro universitet's Swedish publishing site
(``I003/354/5``) and two of its ads, and a real employer's careers page still detected as ReachMee.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import reachmee
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_detects, assert_listing, probe_sized

_ENTRY = "I003/354/5"
CONFIG = {"reachmee_companies": [_ENTRY], "location": "Örebro, Sweden"}
NO_PAGE2 = "a publishing site's list is not paged: one page holds every open ad"


@pytest.mark.live
def test_reachmee_listing_live():
    """The list (the customer script first, for its validator); `locations=False`: Örebro's list has no place column
    (the ad page has the place); `dates=False`: its date column is the deadline."""
    assert_listing("reachmee", reachmee, CONFIG, locations=False, dates=False)


@pytest.mark.live
def test_reachmee_details_live():
    """Two ads' pages: heading, place and text."""
    with probe_sized("reachmee", "details"):
        session = PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=reachmee._HEADERS)
        p = reachmee._entry_parts(_ENTRY)
        employer, rows = reachmee._parse_list(reachmee._read_list(session, p), f"https://{p[0]}/")
        assert rows, "reachmee [details]: no ads on the list"
        now = datetime.now(timezone.utc)
        postings = []
        for row in rows[:2]:
            job = reachmee._parse_job(session.get(row["url"], headers=reachmee._HEADERS).text)
            assert job, f"reachmee [details]: {row['url']} holds no ad"
            postings.append(reachmee._to_posting(row, job, employer or _ENTRY, p, now))
    assert_contract("reachmee", postings, "details", config=CONFIG)


@pytest.mark.live
def test_reachmee_detection_live():
    """A real employer's careers page still shows reachmee and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("reachmee")
