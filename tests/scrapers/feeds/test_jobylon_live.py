"""Live smoke tests for Jobylon, one per mode (#19): company 2420's widget, and a real employer's careers page still
detected as Jobylon.

- listing: the company widget (every open ad's title, place and link); it has no date (the ad page does);
- details: the widget and two ads' pages, whose JSON-LD carries the text and the date.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone
from urllib.parse import urljoin

import pytest

from door.scrapers.feeds import jobylon
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_detects, assert_listing, fail, probe_sized

CONFIG = {"jobylon_companies": ["2420"], "location": "Stockholm"}
NO_PAGE2 = "the company widget lists every open ad at once (no paging)"


@pytest.mark.live
def test_jobylon_listing_live():
    assert_listing("jobylon", jobylon, CONFIG, dates=False)


@pytest.mark.live
def test_jobylon_details_live():
    with probe_sized("jobylon", "details"):
        session = PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=jobylon._HEADERS)
        items = jobylon._fetch_widget(session, "2420")[:2]
        assert items, fail("jobylon", "details", "no ads in the widget")
        ads = {i["id"]: jobylon.parse_ad(session.get(urljoin(jobylon._BASE + "/", i["url"])).text) for i in items}
    assert all(ads.values()), fail("jobylon", "details", f"an ad page without its JSON-LD: {[i['url'] for i in items]}")
    now = datetime.now(timezone.utc)
    assert_contract("jobylon", [jobylon._to_posting(i, ads[i["id"]], "", now) for i in items], "details", config=CONFIG)


@pytest.mark.live
def test_jobylon_detection_live():
    """A real employer's careers page still shows jobylon and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("jobylon")
