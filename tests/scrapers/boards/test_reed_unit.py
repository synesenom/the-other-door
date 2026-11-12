"""Unit tests for the pure helpers of the Reed scraper (reed.co.uk)."""

from datetime import datetime
from pathlib import Path

import pytest

from door.scrapers.boards import reed

_FIX = Path(__file__).parent / "fixtures" / "reed"


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("keyword,location,page,url", [
    ("project manager", "London", 1, "https://www.reed.co.uk/jobs/project-manager-jobs-in-london"),
    ("Project Manager", "London, United Kingdom", 2, "https://www.reed.co.uk/jobs/project-manager-jobs-in-london?pageno=2"),
    ("C++ developer", "Milton Keynes, UK", 1, "https://www.reed.co.uk/jobs/c-developer-jobs-in-milton-keynes"),
    ("accountant", "United Kingdom", 1, "https://www.reed.co.uk/jobs/accountant-jobs"),
    ("accountant", "", 3, "https://www.reed.co.uk/jobs/accountant-jobs?pageno=3"),
    ("nurse", "Remote", 1, "https://www.reed.co.uk/jobs/nurse-jobs"),
])
def test_search_url(keyword, location, page, url):
    assert reed._search_url(keyword, location, page) == url


def test_search_url_never_sends_sortby():
    assert "sortBy" not in reed._search_url("project manager", "London", 2)


def test_results_of_a_search_page():
    count, jobs = reed._parse_results(_html("p1.html"))
    assert count == 30
    assert [j["jobDetail"]["jobId"] for j in jobs] == [57458959, 57131623, 57505209]


def test_a_page_without_the_results_block_is_none():
    assert reed._parse_results("<html><body>Hello</body></html>") is None
    assert reed._parse_results('<script id="__NEXT_DATA__" type="application/json">{"props":{}}</script>') is None
    assert reed._parse_results('<script id="__NEXT_DATA__" type="application/json">not json</script>') is None


def test_card_maps_the_job_detail():
    _, jobs = reed._parse_results(_html("p1.html"))
    card = reed._card(jobs[2])
    assert card["id"] == "57505209"
    assert card["url"] == "https://www.reed.co.uk/jobs/pmo-manager/57505209"
    assert card["title"] == "PMO Manager"
    assert card["company"] == "Deutsche Bank"
    assert card["location"] == "London"
    assert card["created"] == datetime(2026, 10, 29, 14, 17, 36, 40000)
    assert card["external_url"] == ""
    assert card["snippet"].startswith("PMO Manager to support")


def test_card_without_an_id_or_title_is_dropped():
    assert reed._card({"jobDetail": {"jobTitle": "x"}, "url": "/jobs/x/1"}) is None
    assert reed._card({"jobDetail": {"jobId": 5}, "url": "/jobs/x/5"}) is None
    assert reed._card({}) is None


def test_card_keeps_the_external_apply_link():
    raw = {"jobDetail": {"jobId": 9, "jobTitle": "Analyst", "ouName": "Acme", "externalUrl": "https://acme.example/jobs/9",
                         "dateCreated": "2026-10-01T10:00:00"}, "url": "/jobs/analyst/9"}
    assert reed._card(raw)["external_url"] == "https://acme.example/jobs/9"


@pytest.mark.parametrize("value,expected", [
    ("2026-10-14T15:18:04.473", datetime(2026, 10, 14, 15, 18, 4, 473000)),
    ("2026-10-14T15:18:04", datetime(2026, 10, 14, 15, 18, 4)),
    ("2026-10-14T15:18:04.473Z", datetime(2026, 10, 14, 15, 18, 4, 473000)),
    ("", None), (None, None), ("yesterday", None),
])
def test_parse_date(value, expected):
    assert reed._parse_date(value) == expected


def test_description_from_the_json_ld():
    text = reed._parse_description(_html("detail.html"))
    assert text.startswith("Project Manager, Payments (Agile)")
    assert "THE ROLE" in text and "<" not in text


def test_description_none_without_a_job_posting():
    assert reed._parse_description("<html><body>nothing</body></html>") is None
    html = '<script type="application/ld+json">{"@type":"BreadcrumbList"}</script>'
    assert reed._parse_description(html) is None


def test_challenge_detection():
    assert reed._is_challenge("", 403) and reed._is_challenge("", 429)
    assert reed._is_challenge("<title>Just a moment...</title>", 200)
    assert not reed._is_challenge(_html("p1.html"), 200)
