"""Unit tests for the pure helpers of the jobs.ac.uk scraper (academic jobs, server-rendered HTML)."""

from datetime import date, datetime
from pathlib import Path

import pytest

from door.scrapers import sdk
from door.scrapers.boards import jobs_ac_uk

_FIX = Path(__file__).parent / "fixtures" / "jobs_ac_uk"


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("location,page,url", [
    ("London", 1, "https://www.jobs.ac.uk/search/?keywords=research+associate&sortOrder=1&pageSize=25&startIndex=1&locationFacet%5B%5D=london"),
    ("London, UK", 2, "https://www.jobs.ac.uk/search/?keywords=research+associate&sortOrder=1&pageSize=25&startIndex=26&locationFacet%5B%5D=london"),
    ("Newcastle upon Tyne", 1, "https://www.jobs.ac.uk/search/?keywords=research+associate&sortOrder=1&pageSize=25&startIndex=1&locationFacet%5B%5D=newcastle-upon-tyne"),
    ("United Kingdom", 1, "https://www.jobs.ac.uk/search/?keywords=research+associate&sortOrder=1&pageSize=25&startIndex=1"),
    ("", 3, "https://www.jobs.ac.uk/search/?keywords=research+associate&sortOrder=1&pageSize=25&startIndex=51"),
])
def test_search_url_is_newest_first_and_facets_a_known_city(location, page, url):
    assert jobs_ac_uk._search_url("research associate", location, page) == url


def test_search_url_without_facet_for_an_unknown_place():
    assert "locationFacet" not in jobs_ac_uk._search_url("postdoc", "Hebden Bridge", 1)


def test_search_url_sort_order_one_is_date_placed():
    assert "sortOrder=1" in jobs_ac_uk._search_url("postdoc", "London", 1)


def test_cards_of_a_search_page():
    cards = jobs_ac_uk._parse_cards(_html("p1.html"))
    assert [c["id"] for c in cards] == ["1093148", "1093143", "1093009"]
    first = cards[0]
    assert first["title"] == "Postdoctoral Research Associate"
    assert first["company"] == "Queen Mary University of London"
    assert first["department"] == "Barts Cancer Institute"
    assert first["location"] == "London"
    assert first["url"] == "https://www.jobs.ac.uk/job/DTN132/postdoctoral-research-associate"
    assert first["placed"] == (3, 11)
    assert first["salary"].startswith("£39,187 to £52,790")


def test_a_hybrid_location_is_kept_whole():
    cards = jobs_ac_uk._parse_cards(_html("p2.html"))
    assert cards[1]["location"] == "London, Hybrid"


def test_a_page_without_results_block_is_none():
    assert jobs_ac_uk._parse_cards("<html><body>Hello</body></html>") is None


def test_an_empty_result_list_is_an_empty_list():
    assert jobs_ac_uk._parse_cards('<html><h2 class="j-search-content__count"><strong class="job-count">0</strong> Jobs Found</h2></html>') == []


def test_result_count_and_next_link():
    assert jobs_ac_uk._parse_count(_html("p1.html")) == 30
    assert jobs_ac_uk._has_next(_html("p1.html")) is True
    assert jobs_ac_uk._has_next(_html("p2.html")) is False


@pytest.mark.parametrize("day,month,today,expected", [
    (3, 11, date(2026, 11, 3), date(2026, 11, 3)),
    (21, 10, date(2026, 11, 3), date(2026, 10, 21)),
    (28, 12, date(2026, 1, 5), date(2025, 12, 28)),   # a date in the future means last year
    (4, 11, date(2026, 11, 3), date(2025, 11, 4)),
    (29, 2, date(2026, 3, 1), date(2024, 2, 29)),      # 29 Feb: the latest leap year that is not in the future
])
def test_placed_date_infers_the_year(day, month, today, expected):
    assert jobs_ac_uk._placed_date(day, month, today) == datetime.combine(expected, datetime.min.time())


def test_placed_date_of_an_impossible_day_is_none():
    assert jobs_ac_uk._placed_date(31, 2, date(2026, 11, 3)) is None


def test_description_from_json_ld():
    ld = jobs_ac_uk._parse_detail(_html("detail.html"))
    assert ld["description"].startswith("Location: Mile End Road, London E1 4NS")
    assert "A PhD in a relevant subject" in ld["description"] and "<" not in ld["description"]
    assert ld["posted"] == datetime(2026, 11, 3)


def test_detail_without_json_ld_is_none():
    assert jobs_ac_uk._parse_detail("<html><body>no data</body></html>") is None


def test_location_fit_uses_the_city_and_its_commute_area():
    cfg = {"location": "London", "remote": "no"}
    assert sdk.location_fits("London", cfg)
    assert sdk.location_fits("Guildford", cfg)           # the commute area
    assert sdk.location_fits("Remote", cfg)
    assert sdk.location_fits("", cfg)
    assert not sdk.location_fits("Glasgow", cfg)
    assert sdk.location_fits("Glasgow", {**cfg, "remote": "yes"})
