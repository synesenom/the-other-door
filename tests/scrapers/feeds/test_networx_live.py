"""Live smoke tests for Networx's public search by client, one per mode (#19): Havant & South Downs College (client
id 3509), and a real employer's careers page still detected as Networx.

- listing: the client's search page (five adverts: title, place, the ad's first lines); it has no date (the advert does);
- page2: the page's own "load more" call for result page 2 (token and cookie from the search page);
- details: the search page and two adverts' pages, the ad's text and its JSON-LD date.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import networx
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_detects, assert_listing, assert_page2, fail, probe_sized

CID = "3509"
CONFIG = {"networx_companies": [CID], "location": "London"}


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=networx._HEADERS)


def _postings(rows: list[dict], ads=None) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [networx._to_posting(r, (ads or {}).get(r["id"]), "", now) for r in rows if r["cid"] == CID]


@pytest.mark.live
def test_networx_listing_live():
    assert_listing("networx", networx, CONFIG, dates=False)


@pytest.mark.live
def test_networx_page2_live():
    with probe_sized("networx", "page2"):
        session = _session()
        search = networx.parse_search(session.get(networx.search_url(CID)).text)
        assert search["pages"] >= 2, fail("networx", "page2", f"one result page only ({search['pages']})")
        assert search["token"], fail("networx", "page2", "no anti-forgery token on the search page")
        answer = session.post(networx._MORE_URL, data={**search["form"], "ResultsPage": "2"},
                              headers={"__RequestVerificationToken": search["token"], "X-Requested-With": "XMLHttpRequest"})
        _pages, more = networx.parse_more(answer.text)
    assert_page2("networx", _postings(search["rows"]), _postings(more), CONFIG, dates=False)


@pytest.mark.live
def test_networx_details_live():
    with probe_sized("networx", "details"):
        session = _session()
        rows = [r for r in networx.parse_search(session.get(networx.search_url(CID)).text)["rows"] if r["cid"] == CID][:2]
        assert rows, fail("networx", "details", "no adverts to open")
        ads = {r["id"]: networx.parse_ad(session.get(f"{networx._HOST}/Jobs/Advert/{r['id']}", params={"cid": CID}).text)
               for r in rows}
    assert all(ads.values()), fail("networx", "details", f"an advert without its text: {list(ads)}")
    assert_contract("networx", _postings(rows, ads), "details", config=CONFIG)


@pytest.mark.live
def test_networx_detection_live():
    """A real employer's careers page still shows networx and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("networx")
