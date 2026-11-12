"""Unit tests for the LinkedIn guest-endpoint scraper's pure helpers.

The fixtures are synthetic pages in the shape of the logged-out guest endpoints (see
fixtures/linkedin/), made-up cards and ad text with only what the parser reads: a search page
of job cards and one job's detail page.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from door.scrapers.discovery import linkedin

_FIX = Path(__file__).parent / "fixtures" / "linkedin"


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


def test_search_params_carry_keyword_location_start_and_time_filter():
    params = linkedin._search_params("data scientist", "Copenhagen", 10, 3)
    assert params == {"keywords": "data scientist", "location": "Copenhagen", "start": 10, "sortBy": "DD", "f_TPR": "r259200"}


def test_search_params_leave_out_the_time_filter_without_a_cutoff():
    assert "f_TPR" not in linkedin._search_params("x", "y", 0, None)


def test_the_time_filter_is_the_whole_days_since_the_cutoff():
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    assert linkedin._time_filter_days(now - timedelta(hours=30), now) == 2
    assert linkedin._time_filter_days(None, now) is None


def test_parse_cards_reads_id_title_company_location_date_and_url():
    cards = linkedin._parse_cards(_fx("search_results.html"))
    assert [c["platform_id"] for c in cards] == ["4100000001", "4100000002", "4100000003", "4100000004"]
    first = cards[0]
    assert first["title"] == "Data Scientist, Advanced Analytics & AI"
    assert first["company"] == "Acme Defence Systems"
    assert first["location"] == "Aarhus, Central Denmark Region, Denmark"
    assert first["posted_at"] == datetime(2026, 10, 10, tzinfo=timezone.utc)
    assert first["url"] == "https://www.linkedin.com/jobs/view/4100000001"


def test_parse_cards_of_a_page_without_cards_is_empty():
    assert linkedin._parse_cards("<!DOCTYPE html>\n") == []


def test_parse_cards_skips_a_card_without_an_id_or_a_title():
    html = (
        '<li><div class="base-search-card"><h3 class="base-search-card__title">No id</h3></div></li>'
        '<li><div class="base-search-card" data-entity-urn="urn:li:jobPosting:9"></div></li>'
    )
    assert linkedin._parse_cards(html) == []


def test_parse_detail_reads_description_and_criteria():
    detail = linkedin._parse_detail(_fx("detail_4100000001.html"))
    assert detail["description"].startswith("Do you want to build machine learning models")
    assert "Seniority level: Associate" in detail["criteria"]
    assert "Employment type: Full-time" in detail["criteria"]
    assert detail["apply_type"] == "external"  # the offsite-apply icon on the Apply button
    assert detail["apply_url"] is None  # the guest page does not expose where


def test_parse_detail_takes_an_offsite_apply_url_from_code_applyurl():
    html = '<code id="applyUrl" style="display:none"><!--"https://acme.example/jobs/1?utm=x"--></code>'
    detail = linkedin._parse_detail(html)
    assert detail["apply_type"] == "external"
    assert detail["apply_url"] == "https://acme.example/jobs/1?utm=x"


def test_parse_detail_unwraps_linkedins_safety_redirect():
    html = '<code id="applyUrl"><!--"https://www.linkedin.com/safety/go/?url=https%3A%2F%2Facme.example%2Fj%2F1&amp;trk=x"--></code>'
    assert linkedin._parse_detail(html)["apply_url"] == "https://acme.example/j/1"


def test_parse_detail_without_an_apply_marker_is_unknown():
    detail = linkedin._parse_detail('<div class="show-more-less-html__markup">Hello</div>')
    assert detail["description"] == "Hello"
    assert detail["apply_type"] == "unknown" and detail["apply_url"] is None


def test_an_authwall_or_login_url_is_a_wall():
    assert linkedin._is_wall("https://www.linkedin.com/authwall?trk=bf&original_referer=")
    assert linkedin._is_wall("https://www.linkedin.com/uas/login?session_redirect=x")
    assert linkedin._is_wall("https://www.linkedin.com/checkpoint/challenge/abc")
    assert not linkedin._is_wall("https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/1")


def test_search_params_ask_for_the_newest_first():
    assert linkedin._search_params("x", "y", 0, None)["sortBy"] == "DD"
