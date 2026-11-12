"""Unit tests for the pure helpers of the NHS Jobs scraper (server-rendered HTML)."""

from datetime import datetime
from pathlib import Path

import pytest

from door.scrapers.boards import nhs_jobs

_FIX = Path(__file__).parent / "fixtures" / "nhs_jobs"


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("location,page,url", [
    ("London", 1, "https://www.jobs.nhs.uk/candidate/search/results?keyword=project+manager&location=London&sort=publicationDateDesc&page=1"),
    ("London, United Kingdom", 2, "https://www.jobs.nhs.uk/candidate/search/results?keyword=project+manager&location=London&sort=publicationDateDesc&page=2"),
    ("United Kingdom", 1, "https://www.jobs.nhs.uk/candidate/search/results?keyword=project+manager&sort=publicationDateDesc&page=1"),
    ("", 3, "https://www.jobs.nhs.uk/candidate/search/results?keyword=project+manager&sort=publicationDateDesc&page=3"),
])
def test_search_url_is_newest_first_and_names_a_known_city(location, page, url):
    assert nhs_jobs._search_url("project manager", location, page) == url


@pytest.mark.parametrize("text,clean", [
    ("London E13 8AL", "London"),
    ("London SW17 0QT", "London"),
    ("Leeds LS1 4AP", "Leeds"),
    ("Remote", "Remote"),
    ("Newcastle upon Tyne NE1 4LP", "Newcastle upon Tyne"),
    ("Manchester", "Manchester"),
    ("Manchester M13 9LL, Speke L24 8RB, London SW17 0RB, Filton", "Manchester, Speke, London, Filton"),
    ("", ""),
])
def test_location_text_drops_the_postcode(text, clean):
    assert nhs_jobs._clean_location(text) == clean


def test_cards_of_a_search_page():
    cards = nhs_jobs._parse_cards(_html("p1.html"))
    assert [c["id"] for c in cards] == ["C9363-26-1283", "C9200-26-1002", "C9200-26-1001"]
    last = cards[2]
    assert last["title"] == "IDT Change Manager"
    assert last["company"] == "St George's University Hospitals NHS Foundation Trust"
    assert last["location"] == "London"
    assert last["url"] == "https://www.jobs.nhs.uk/candidate/jobadvert/C9200-26-1001"
    assert last["posted"] == datetime(2026, 11, 3)
    assert last["salary"] == "£66,274 to £73,496 a year" or last["salary"].startswith("£")
    assert last["contract"]


def test_a_page_without_results_block_is_none():
    assert nhs_jobs._parse_cards("<html><body>Service Domain Information</body></html>") is None


def test_an_empty_result_list_is_an_empty_list():
    assert nhs_jobs._parse_cards('<html><h1 data-test="search-result-query">0 jobs found for x</h1><ul class="nhsuk-list search-results"></ul></html>') == []


def test_next_link():
    assert nhs_jobs._has_next(_html("p1.html")) is True
    assert nhs_jobs._has_next(_html("p1.html").replace('data-test="search-next-page"', "")) is False


def test_the_detail_page_gives_text_and_the_exact_date():
    detail = nhs_jobs._parse_detail(_html("detail.html"))
    assert detail["posted"] == datetime(2026, 11, 3)
    text = detail["description"]
    assert "change manager to join its change team" in text and "gap analysis" in text
    assert "<" not in text and "\n" in text


def test_a_page_without_description_has_no_detail():
    assert nhs_jobs._parse_detail("<html><body>no data</body></html>") is None


@pytest.mark.parametrize("text,date", [("3 November 2026", datetime(2026, 11, 3)), ("03 November 2026", datetime(2026, 11, 3)),
                                       ("12 Jan 2026", datetime(2026, 1, 12)), ("soon", None), ("", None)])
def test_dates_have_a_year(text, date):
    assert nhs_jobs._parse_date(text) == date


def test_parse_detail_reads_the_jobs_own_place_once():
    detail = nhs_jobs._parse_detail(_html("detail.html"))
    assert detail["location"] == "London"
    page = _html("detail.html").replace('id="employer_town">London', 'id="employer_town">Birmingham').replace(
        'id="employer_county"></p>', 'id="employer_county">West Midlands</p>')
    assert nhs_jobs._parse_detail(page)["location"] == "Birmingham, West Midlands"
    bare = page.replace('id="employer_town">Birmingham', 'id="employer_town"></p><p id="x"').replace(
        'West Midlands', "")
    assert nhs_jobs._parse_detail(bare)["location"] == ""
