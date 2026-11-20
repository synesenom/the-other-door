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


def test_description_none_without_a_job_posting():
    assert reed._parse_description("<html><body>nothing</body></html>") is None
    html = '<script type="application/ld+json">{"@type":"BreadcrumbList"}</script>'
    assert reed._parse_description(html) is None


def test_parse_date_is_naive_even_for_a_z_date():
    assert reed._parse_date("2026-11-20T10:00:00Z").tzinfo is None


def test_the_first_ad_with_a_description_is_read_and_none_when_its_text_is_empty():
    assert reed._parse_description('<script type="application/ld+json">{"@type": "JobPosting", "title": "A", "description": ""}</script><script type="application/ld+json">{"@type": "JobPosting", "title": "B", "description": "<p>Second</p>"}</script>') == "Second"
    assert reed._parse_description('<script type="application/ld+json">{"@type": "JobPosting", "title": "A", "description": "<p></p>"}</script><script type="application/ld+json">{"@type": "JobPosting", "title": "B", "description": "<p>Second</p>"}</script>') is None
