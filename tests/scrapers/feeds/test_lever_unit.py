"""Unit tests for Lever pure helpers (unit layer).

Covers _location_text, _parse_date, _description_text, and zero-result warning
behaviour.
Pure and offline.
"""

import json
from datetime import datetime

import pytest

from door.scrapers.feeds import lever
from paths import TESTS_DIR


# --------------------------------------------------------------------------- #
# _location_text
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "job,expected",
    [
        ({"categories": {"location": "Copenhagen, Denmark"}}, "Copenhagen, Denmark"),
        ({}, ""),
    ],
)
def test_location_text(job, expected):
    assert lever._location_text(job) == expected


# --------------------------------------------------------------------------- #
# _parse_date
# --------------------------------------------------------------------------- #

def test_parse_date_ms_timestamp():
    """A millisecond Unix timestamp is converted to an ISO string."""
    # 1746100800000 ms = 2025-05-01T12:00:00 UTC
    ms = 1746100800000
    result = lever._parse_date(ms)
    assert result is not None
    dt = datetime.fromisoformat(result)
    assert dt.year == 2025
    assert dt.month == 5
    assert dt.day == 1


def test_parse_date_zero():
    """A zero millisecond timestamp maps to epoch start."""
    result = lever._parse_date(0)
    assert result is not None
    dt = datetime.fromisoformat(result)
    assert dt.year == 1970
    assert dt.month == 1
    assert dt.day == 1


def test_parse_date_float_returns_none():
    """Float input (edge case) returns None."""
    assert lever._parse_date(1.5) is None


# --------------------------------------------------------------------------- #
# Zero-result warning
# --------------------------------------------------------------------------- #

def test_scrape_missing_key_returns_empty():
    """When lever_companies is absent, scrape() returns an empty list."""
    result = lever.scrape({})
    assert result == []


# --------------------------------------------------------------------------- #
# _description_text
# --------------------------------------------------------------------------- #

def _full_postings() -> list[dict]:
    return json.loads((TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "lever" / "postings_full.json").read_text(encoding="utf-8"))


def test_description_text_includes_lists_and_additional():
    # Real Spotify posting: `descriptionPlain` is only the intro; the duties and
    # requirements live in `lists`, the closing text in `additionalPlain`.
    job = _full_postings()[0]
    text = lever._description_text(job)
    assert text.startswith(job["descriptionPlain"].strip()[:60])
    assert "What You'll Do\n" in text
    assert "Develop and maintain mobile client components" in text
    assert "Who You Are" in text
    assert "Spotify is an equal opportunity employer." in text
    assert "<" not in text
    assert len(text) > 2 * len(job["descriptionPlain"])


def test_description_text_falls_back_to_html_description():
    # Real posting whose `descriptionPlain` is empty but `description` is not.
    job = _full_postings()[1]
    assert not job["descriptionPlain"]
    text = lever._description_text(job)
    assert text.startswith("The Platform team creates the technology")
    assert "<" not in text


def test_description_text_minimal_job():
    assert lever._description_text({"descriptionPlain": "Just this."}) == "Just this."
    assert lever._description_text({}) == ""


@pytest.mark.parametrize("entry, expected", [
    ("siteimprove", ("siteimprove", None)),
    ("https://jobs.eu.lever.co/siteimprove", ("siteimprove", "https://api.eu.lever.co/v0/postings")),
    ("jobs.lever.co/acme/1234-abcd", ("acme", "https://api.lever.co/v0/postings")),
    (" Acme ", ("acme", None)),
])
def test_company_accepts_a_slug_or_a_board_url(entry, expected):
    """Issue #227: a jobs.eu.lever.co URL pins the EU host; a bare slug tries both."""
    assert lever._company(entry) == expected

# --- feed detection (issue #282) ---

def _d(det):
    return None if det is None else (det.platform, det.entry)


@pytest.mark.parametrize("url, slug", [
    ("https://jobs.lever.co/kavak/abc-123", "kavak"), ("https://jobs.eu.lever.co/siteimprove", "siteimprove"),
    ("https://jobs.lever.co/", None), ("https://lever.co/kavak", None),
])
def test_detect_url(url, slug):
    det = lever.detect_url(url)
    assert (det.entry if det else None) == slug


def test_a_lever_name_probe_tries_the_us_host_then_the_eu_one():
    us, eu = lever.name_probes("acme")
    assert us.url == "https://api.lever.co/v0/postings/acme" and us.key is None and us.params == {"mode": "json"}
    assert eu.url == "https://api.eu.lever.co/v0/postings/acme" and eu.evidence == "Lever account acme (EU host)"
    assert lever.feed_url("acme") is None
