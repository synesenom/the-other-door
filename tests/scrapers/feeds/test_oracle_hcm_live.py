"""Live smoke tests for Oracle Cloud HCM's public candidate-experience feed, one per mode (#19): Danske Bank's career
site (``ejqi.fa.ocs.oraclecloud.eu/CX_1001``), and a real employer's careers page still detected as Oracle Cloud HCM.

- listing: page 1 of the job search (title, place, date and a short description);
- page2: the search in pages of `_LIMIT` requisitions (the scraper asks 25), offsets 0 and `_LIMIT`;
- details: the search and two requisitions' details, which hold the whole text.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import oracle_hcm
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_detects, assert_listing, assert_page2, fail, probe_sized

CONFIG = {"oracle_hcm_companies": ["ejqi.fa.ocs.oraclecloud.eu/CX_1001"], "location": "Copenhagen"}
_HOST, _SITE = oracle_hcm._entry(CONFIG["oracle_hcm_companies"][0])
_LIMIT = 10


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=oracle_hcm._HEADERS)


def _postings(items: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [oracle_hcm._to_posting(i, _HOST, _SITE, oracle_hcm._company_name(_HOST), now) for i in items]


@pytest.mark.live
def test_oracle_hcm_listing_live():
    assert_listing("oracle_hcm", oracle_hcm, CONFIG)


@pytest.mark.live
def test_oracle_hcm_page2_live():
    with probe_sized("oracle_hcm", "page2"):
        session = _session()
        pages = [oracle_hcm._page(session, _HOST, _SITE, offset, _LIMIT)[0] for offset in (0, _LIMIT)]
    assert_page2("oracle_hcm", _postings(pages[0]), _postings(pages[1]), CONFIG)


@pytest.mark.live
def test_oracle_hcm_details_live():
    with probe_sized("oracle_hcm", "details"):
        session = _session()
        items = oracle_hcm._page(session, _HOST, _SITE, 0, _LIMIT)[0][:2]
        assert items, fail("oracle_hcm", "details", "no requisitions to open")
        postings = _postings(items)
        for item, posting in zip(items, postings):
            detail = oracle_hcm._first(session.get(oracle_hcm._detail_url(_HOST, _SITE, str(item["Id"]))).json())
            posting["description"] = oracle_hcm._description(detail)
    assert_contract("oracle_hcm", postings, "details", config=CONFIG)


@pytest.mark.live
def test_oracle_hcm_detection_live():
    """A real employer's careers page still shows oracle_hcm and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("oracle_hcm")
