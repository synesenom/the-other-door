"""Unit tests for the pure helpers in the Workable job-search scraper. No network."""

from datetime import datetime, timezone

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import workable


def _job(**over) -> dict:
    job = {
        "id": "7c2eaad3-0c5e-4cf8-a1af-ac2709a7c907",
        "title": "  Senior Data Scientist  ",
        "description": "<p>Build <strong>models</strong> &amp; ship them.</p>",
        "requirementsSection": "<ul><li>Python</li></ul>",
        "benefitsSection": "",
        "url": "https://jobs.workable.com/view/abc/senior-data-scientist",
        "location": {"city": "London", "subregion": "England", "countryName": "United Kingdom"},
        "created": "2026-09-21T21:38:50.090Z",
        "company": {"title": "Our Future Health"},
        "workplace": "hybrid",
    }
    job.update(over)
    return job


# _location_text ----------------------------------------------------------- #

def test_location_text_city_and_country():
    assert workable._location_text(_job()) == "London, United Kingdom"


def test_location_text_remote_is_marked():
    job = _job(location={"city": "", "subregion": None, "countryName": "Denmark"}, workplace="remote")
    assert workable._location_text(job) == "Remote, Denmark"


def test_location_text_missing():
    assert workable._location_text(_job(location=None, workplace=None)) == ""


# _description_text --------------------------------------------------------- #

def test_description_joins_sections_as_plain_text():
    text = workable._description_text(_job())
    assert "<" not in text
    assert "Build models & ship them." in text
    assert "Python" in text


def test_description_empty_when_no_sections():
    assert workable._description_text(_job(description=None, requirementsSection=None)) == ""


# _search_params ------------------------------------------------------------ #

def test_search_params_with_location_and_token():
    assert workable._search_params("data scientist", "Copenhagen", "tok") == {
        "query": "data scientist", "location": "Copenhagen", "pageToken": "tok"}


def test_search_params_omits_empty_location_and_token():
    assert workable._search_params("data scientist", "", None) == {"query": "data scientist"}


# _keywords ---------------------------------------------------------------- #

def test_keywords_prefer_search_keywords_then_role_targets():
    assert workable._keywords({"search_keywords": ["a"], "role_targets": ["b"]}) == ["a"]
    assert workable._keywords({"search_keywords": [], "role_targets": ["b"]}) == ["b"]
    assert workable._keywords({}) == []


# _to_posting --------------------------------------------------------------- #

def test_to_posting_maps_fields_and_validates():
    scraped_at = datetime(2026, 10, 8, tzinfo=timezone.utc)
    p = workable._to_posting(_job(), scraped_at)
    JobPosting.model_validate(p)
    assert p["source"] == "workable"
    assert p["title"] == "Senior Data Scientist"
    assert p["company"] == "Our Future Health"
    assert p["location"] == "London, United Kingdom"
    assert p["platform_id"] == "7c2eaad3-0c5e-4cf8-a1af-ac2709a7c907"
    assert p["url"] == p["apply_url"] == "https://jobs.workable.com/view/abc/senior-data-scientist"
    assert p["apply_type"] == "external"
    assert p["posted_at"].startswith("2026-09-21")
    # job ids allow only [a-z0-9-], so the prefix is hyphenated
    assert p["id"] == "workable." + p["platform_id"].lower()
    assert "Python" in p["description"]


def test_to_posting_without_company_falls_back_to_unknown():
    p = workable._to_posting(_job(company=None), datetime.now(timezone.utc))
    JobPosting.model_validate(p)
    assert p["company"] == "Unknown"

# --- feed detection (issue #282) ---

def _d(det):
    return None if det is None else (det.platform, det.entry)


def test_detect_url():
    assert _d(workable.detect_url("https://apply.workable.com/dreamdata/j/497E870DCF/")) == ("workable", "dreamdata")
    assert workable.detect_url("https://apply.workable.com/j/497E870DCF") is None
    assert workable.detect_url("https://jobs.workable.com/view/abc") is None


def test_a_workable_name_probe_is_the_widget_api():
    (probe,) = workable.name_probes("acme")
    assert (probe.url, probe.key) == ("https://apply.workable.com/api/v1/widget/accounts/acme", "jobs")
    assert workable.feed_url("acme") is None
