"""Live smoke tests for Emply, one per mode (#19): DanChurchAid's vacancy API (issue #437), Aarhus University's
page that embeds its Emply list (issue #431), and a real employer's careers page still detected as Emply.

- listing: page 1 of DanChurchAid's ``get-page`` answer, which carries every ad's text;
- page2: the same list in pages of `_PAGE` vacancies (the scraper asks 50), offsets 0 and `_PAGE`;
- details: Aarhus University's page and two vacancies' pages, whose ad text the scraper reads.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import emply
from door.scrapers.http_client import PoliteSession
from live_utils import assert_contract, assert_detects, assert_listing, assert_page2, fail, probe_sized

CONFIG = {"emply_tenants": ["dca"], "location": "Copenhagen"}
AU_PAGE = "https://international.au.dk/about/profile/vacant-positions/"
_PAGE = 5  # vacancies a page in the page2 test, so a small tenant has a second page


def _session(headers=None) -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0, headers=headers or emply._HEADERS)


@pytest.mark.live
def test_emply_listing_live():
    assert_listing("emply", emply, CONFIG, descriptions=True)


@pytest.mark.live
def test_emply_page2_live(monkeypatch):
    monkeypatch.setattr(emply, "_PAGE", _PAGE)
    with probe_sized("emply", "page2"):
        session = _session()
        pages = [emply._page(session, "dca", offset)["vacancies"] for offset in (0, _PAGE)]
    now = datetime.now(timezone.utc)
    postings = [[emply._to_posting(v, "dca", now) for v in emply._vacancies(p)] for p in pages]
    assert_page2("emply", postings[0], postings[1], CONFIG, descriptions=True)


@pytest.mark.live
def test_emply_details_live():
    """Aarhus University's embedded list (department in the title) and two vacancies' own ad text."""
    with probe_sized("emply", "details"):
        session = _session({"Accept": "text/html"})
        html = session.get(AU_PAGE).text
        name = emply._embedded_name(html)
        today = emply._today()
        vacancies = [v for v in emply.embedded_vacancies(html) if emply._open(v, today)][:2]
        assert vacancies, fail("emply", "details", f"no open vacancy embedded in {AU_PAGE}")
        now = datetime.now(timezone.utc)
        postings = [emply._embedded_posting(v, AU_PAGE, name, now) for v in vacancies]
        for p in postings:
            p["description"] = emply._embedded_description(session.get(p["url"]).text)
    assert name == "Aarhus University", fail("emply", "details", f"the page names {name!r}, not Aarhus University")
    assert_contract("emply", postings, "details", config={"location": "Aarhus"})


@pytest.mark.live
def test_emply_detection_live():
    """A real employer's careers page still shows emply and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("emply")
