"""Unit tests for Greenhouse pure helpers (unit layer).

Covers _location_text, and zero-result warning
behaviour.
Pure and offline.
"""

import pytest

from door.scrapers.feeds import greenhouse


# --------------------------------------------------------------------------- #
# _location_text
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "job,expected",
    [
        ({"location": {"name": "Copenhagen, Denmark"}}, "Copenhagen, Denmark"),
        ({}, ""),
    ],
)
def test_location_text(job, expected):
    assert greenhouse._location_text(job) == expected


# --------------------------------------------------------------------------- #
# Zero-result warning
# --------------------------------------------------------------------------- #

def test_scrape_missing_key_returns_empty():
    """When greenhouse_boards is absent, scrape() returns an empty list."""
    result = greenhouse.scrape({})
    assert result == []


@pytest.mark.parametrize("entry, token", [
    ("trustpilot", "trustpilot"),
    ("https://job-boards.greenhouse.io/trustpilot", "trustpilot"),
    ("https://job-boards.eu.greenhouse.io/trustpilot/jobs/123", "trustpilot"),
    ("boards.greenhouse.io/acme", "acme"),
    ("https://boards.greenhouse.io/embed/job_board?for=acme&b=x", "acme"),
    ("  Acme ", "acme"),
])
def test_board_token_accepts_a_token_or_a_board_url(entry, token):
    """Issue #227: `greenhouse_boards` takes the token or the board's URL."""
    assert greenhouse._board_token(entry) == token

# --- feed detection (issue #282) ---

def _d(det):
    return None if det is None else (det.platform, det.entry)


@pytest.mark.parametrize("url, expected", [
    ("https://job-boards.greenhouse.io/trustpilot/jobs/7339851", "trustpilot"),
    ("https://boards.greenhouse.io/embed/job_board?for=acme", "acme"),
    ("https://job-boards.eu.greenhouse.io/pandora", "pandora"),
    ("https://boards.eu.greenhouse.io/", None),
    ("https://www.greenhouse.com/", None),
])
def test_detect_url(url, expected):
    det = greenhouse.detect_url(url)
    assert (det.entry if det else None) == expected
    assert det is None or det.platform == "greenhouse"


def test_a_greenhouse_name_probe_is_the_board_api():
    (probe,) = greenhouse.name_probes("acme")
    assert (probe.url, probe.key) == ("https://boards-api.greenhouse.io/v1/boards/acme/jobs", "jobs")
    assert probe.evidence == "Greenhouse board acme" and greenhouse.feed_url("acme") is None
