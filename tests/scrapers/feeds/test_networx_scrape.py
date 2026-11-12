"""Fixture tests for Networx: Havant & South Downs College's search (client id 3509, two result pages) and Wates's empty
one (1491), real logged-out answers, trimmed and their text rewritten. The site has only English ads."""

from urllib.parse import parse_qs

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local, drain_pushback
from door.scrapers.feeds import networx
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "networx"
_BASE = "https://www.networxrecruitment.com"
_SEARCH = f"{_BASE}/Website/Search?SelectedEmployers=3509"
_MORE = f"{_BASE}/Website/JobSearchMoreResults"
_IDS = ["4368134", "4361924", "4359336", "4359362", "4359422"]
_CFG = {"networx_companies": ["3509"]}


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _ad(jid: str, cid: str = "3509") -> str:
    return f"{_BASE}/Jobs/Advert/{jid}?cid={cid}"


def _mock_all(ads: tuple[str, ...] = tuple(_IDS)):
    responses.add(responses.GET, _SEARCH, body=_fx("search_3509_page1.html"))
    responses.add(responses.POST, _MORE, body=_fx("more_3509_page2.json"), content_type="application/json")
    for jid in ads:
        responses.add(responses.GET, _ad(jid), body=_fx(f"ad_{jid}.html"))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_pages_through_the_results_and_maps_every_ad_with_its_text():
    _mock_all()

    postings = networx.scrape(_CFG)

    assert [p["platform_id"] for p in postings] == _IDS   # (the college's page-two row repeating a page-one ad comes once)
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "networx" and p["company"] == "Havant & South Downs College"
        assert p["description"] and "<" not in p["description"]
        assert p["url"] == _ad(p["platform_id"])
    lecturer = postings[0]
    assert lecturer["id"] == "networx.4368134" and lecturer["title"] == "Bank Lecturer (Adult Learning)"
    assert lecturer["location"] == "Havant" and lecturer["posted_at"].startswith("2026-11-03")
    assert lecturer["description"].startswith("Salary: £29.03ph - £37.92ph (dependant on experience)\n\nThe Vacancy")
    assert postings[4]["title"] == "Lecturer of Access to HE: Science"
    assert len(responses.calls) == 7   # the search, the second page, then one advert each


@responses.activate
def test_the_next_page_is_asked_the_way_the_site_asks_it():
    _mock_all()

    networx.scrape(_CFG)

    post = next(c.request for c in responses.calls if c.request.method == "POST")
    assert post.headers["__RequestVerificationToken"] == "REPLACED-TOKEN"
    form = parse_qs(post.body)
    assert form["SelectedEmployers"] == ["3509"] and form["ResultsPage"] == ["2"]
    assert form["maxSalary"] == ["999999999"]


@responses.activate
def test_known_ids_skip_the_advert_requests():
    _mock_all(("4359422",))

    postings = networx.scrape(_CFG, known_ids=frozenset(_IDS[:4]))

    assert [p["platform_id"] for p in postings] == ["4359422"]
    assert len(responses.calls) == 3


@responses.activate
def test_the_followed_name_wins():
    _mock_all()

    postings = networx.scrape({**_CFG, "_names": {"networx_companies": {"3509": "HSDC"}}})

    assert {p["company"] for p in postings} == {"HSDC"}


@responses.activate
def test_a_link_as_the_entry_is_read_from_its_client():
    _mock_all()

    postings = networx.scrape({"networx_companies": [_ad("4361924")]})

    assert len(postings) == 5


@responses.activate
def test_the_same_client_listed_by_two_entries_gives_its_ads_once():
    _mock_all()

    postings = networx.scrape({"networx_companies": ["3509", _SEARCH]})

    assert [p["platform_id"] for p in postings] == _IDS


@responses.activate
def test_a_client_without_adverts_is_quiet_and_its_sponsored_neighbours_are_not_taken_for_its_own():
    responses.add(responses.GET, f"{_BASE}/Website/Search?SelectedEmployers=1491", body=_fx("search_1491_empty.html"))

    drain_errors()
    assert networx.scrape({"networx_companies": ["1491"]}) == []
    assert drain_errors() == {}
    assert len(responses.calls) == 1


@responses.activate
def test_a_failing_search_is_a_recorded_error_and_the_other_client_is_kept():
    responses.add(responses.GET, f"{_BASE}/Website/Search?SelectedEmployers=99", status=500)
    _mock_all()

    drain_errors()
    assert len(networx.scrape({"networx_companies": ["99", "3509"]})) == 5
    assert "99" in drain_errors()["networx"][0]


@responses.activate
def test_a_page_that_is_no_search_result_is_a_recorded_error_not_an_empty_board():
    responses.add(responses.GET, _SEARCH, body="<html><h1>Error</h1></html>")

    drain_errors()
    assert networx.scrape(_CFG) == []
    assert "3509" in drain_errors()["networx"][0]


@responses.activate
def test_a_failing_next_page_is_recorded_and_the_first_page_is_kept():
    responses.add(responses.GET, _SEARCH, body=_fx("search_3509_page1.html"))
    responses.add(responses.POST, _MORE, status=500)
    for jid in _IDS[:3]:
        responses.add(responses.GET, _ad(jid), body=_fx(f"ad_{jid}.html"))

    drain_errors()
    postings = networx.scrape(_CFG)

    assert [p["platform_id"] for p in postings] == _IDS[:3]
    assert drain_errors()["networx"]


@responses.activate
def test_a_failing_advert_is_recorded_and_the_others_kept():
    responses.add(responses.GET, _SEARCH, body=_fx("search_3509_page1.html"))
    responses.add(responses.POST, _MORE, body=_fx("more_3509_page2.json"))
    responses.add(responses.GET, _ad("4368134"), status=500)
    responses.add(responses.GET, _ad("4361924"), body="<html><h1>Error</h1></html>")
    for jid in _IDS[2:]:
        responses.add(responses.GET, _ad(jid), body=_fx(f"ad_{jid}.html"))

    drain_errors()
    postings = networx.scrape(_CFG)

    assert [p["platform_id"] for p in postings] == _IDS[2:]
    assert len(drain_errors()["networx"]) == 2


@responses.activate
@pytest.mark.parametrize("status", [429, 403])
def test_pushback_on_the_search_is_recorded_and_stops_the_client(status):
    responses.add(responses.GET, _SEARCH, status=status)

    drain_errors()
    drain_pushback("networx")
    assert networx.scrape(_CFG) == []

    assert drain_pushback("networx") is True
    assert drain_errors()["networx"]


@responses.activate
def test_pushback_on_an_advert_stops_the_rest_of_the_client():
    responses.add(responses.GET, _SEARCH, body=_fx("search_3509_page1.html"))
    responses.add(responses.POST, _MORE, body=_fx("more_3509_page2.json"))
    responses.add(responses.GET, _ad("4368134"), status=429)

    drain_pushback("networx")
    networx.scrape(_CFG)

    assert drain_pushback("networx") is True
    assert [c.request.url for c in responses.calls].count(_ad("4361924")) == 0


@responses.activate
def test_a_page_that_repeats_the_first_ends_the_paging():
    html = _fx("search_3509_page1.html").replace('id="TotalResultsPageCount" name="TotalResultsPageCount" type="hidden" value="2"',
                                                'id="TotalResultsPageCount" name="TotalResultsPageCount" type="hidden" value="500"')
    responses.add(responses.GET, _SEARCH, body=html)
    responses.add(responses.POST, _MORE, body=_fx("more_3509_page2.json"))
    for jid in _IDS[:3] + _IDS[3:]:
        responses.add(responses.GET, _ad(jid), body=_fx(f"ad_{jid}.html"))

    postings = networx.scrape(_CFG)

    assert len(postings) == 5
    assert [c.request.method for c in responses.calls].count("POST") == 2   # page 2 adds ads, page 3 only repeats them


@responses.activate
def test_a_posting_in_another_country_is_dropped():
    _mock_all()
    html = _fx("search_3509_page1.html").replace("</span> Havant</p>", "</span> Lyon, FR</p>", 1)
    responses.replace(responses.GET, _SEARCH, body=html)

    drain_non_local("networx")
    postings = networx.scrape({**_CFG, "location": "Southampton", "_country": "gb"})

    assert "4368134" not in [p["platform_id"] for p in postings] and len(postings) == 4
    assert drain_non_local("networx") == 1


def test_scrape_without_entries_is_empty():
    assert networx.scrape({}) == []
    assert networx.probe({}) is None


# --- probe ---

@responses.activate
def test_probe_reads_the_first_search_page_only():
    responses.add(responses.GET, _SEARCH, body=_fx("search_3509_page1.html"))

    drain_errors()
    result = networx.probe(_CFG)

    assert result["structure_ok"] is True and len(result["postings"]) == 3
    assert len(responses.calls) == 1
    assert drain_errors() == {}


@responses.activate
def test_probe_of_a_client_without_adverts_still_has_its_structure():
    responses.add(responses.GET, f"{_BASE}/Website/Search?SelectedEmployers=1491", body=_fx("search_1491_empty.html"))

    result = networx.probe({"networx_companies": ["1491"]})

    assert result["structure_ok"] is True and result["postings"] == []


@responses.activate
def test_probe_of_a_page_without_its_results_block_has_no_structure():
    responses.add(responses.GET, _SEARCH, body=_fx("search_3509_page1.html").replace("results-container", "other"))

    result = networx.probe(_CFG)

    assert result["structure_ok"] is False and result["reason"]


@responses.activate
def test_probe_connection_error_is_unreachable():
    responses.add(responses.GET, _SEARCH, body=requests.ConnectionError("down"))

    result = networx.probe(_CFG)

    assert result.get("unreachable") and result["structure_ok"] is False


@responses.activate
@pytest.mark.parametrize("status", [401, 403])
def test_probe_401_and_403_are_a_wall(status):
    responses.add(responses.GET, _SEARCH, status=status)

    assert networx.probe(_CFG).get("wall")
