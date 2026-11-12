"""Unit tests for TeamTailor pure helpers (unit layer).

Covers _location_text, _platform_id, and
zero-result / missing-config-key behaviour.
Pure and offline.
"""

import pytest

from door.scrapers.feeds import teamtailor


# --------------------------------------------------------------------------- #
# _location_text
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "item,expected",
    [
        (
            {
                "_jobposting": {
                    "jobLocation": [
                        {"@type": "Place", "address": {
                            "addressLocality": "Stockholm",
                            "addressCountry": "SE",
                        }},
                        {"@type": "Place", "address": {
                            "addressLocality": "Umeå",
                            "addressCountry": "SE",
                        }},
                    ]
                }
            },
            "Stockholm, SE; Umeå, SE",
        ),
        ({"_jobposting": {"jobLocation": []}}, ""),
    ],
)
def test_location_text(item, expected):
    assert teamtailor._location_text(item) == expected


def test_location_text_city_only():
    item = {"_jobposting": {"jobLocation": [
        {"@type": "Place", "address": {"addressLocality": "Remote"}}
    ]}}
    assert teamtailor._location_text(item) == "Remote"


def test_location_text_ignores_address_region():
    """addressRegion is unreliable per research and must not be used."""
    item = {
        "_jobposting": {
            "jobLocation": [
                {"@type": "Place", "address": {
                    "addressLocality": "Malmö",
                    "addressCountry": "SE",
                    "addressRegion": "Some Inconsistent Value",
                }}
            ]
        }
    }
    assert teamtailor._location_text(item) == "Malmö, SE"


# --------------------------------------------------------------------------- #
# _platform_id
# --------------------------------------------------------------------------- #

def test_platform_id_prefers_jobposting_identifier():
    item = {"id": "some-uuid", "_jobposting": {"identifier": {"value": 8124466}}}
    assert teamtailor._platform_id(item) == "8124466"


def test_platform_id_falls_back_to_top_level_id():
    item = {"id": "some-uuid", "_jobposting": {}}
    assert teamtailor._platform_id(item) == "some-uuid"


# --------------------------------------------------------------------------- #
# scrape() config edge cases / zero-result warning
# --------------------------------------------------------------------------- #

def test_scrape_missing_key_returns_empty():
    """When teamtailor_companies is absent, scrape() returns an empty list."""
    result = teamtailor.scrape({})
    assert result == []


@pytest.mark.parametrize("entry, base", [
    ("templafy", "https://templafy.teamtailor.com"),
    (" Templafy ", "https://templafy.teamtailor.com"),
    ("careers.veo.co", "https://careers.veo.co"),
    ("https://careers.veo.co/jobs", "https://careers.veo.co"),
    ("https://podimo.teamtailor.com/", "https://podimo.teamtailor.com"),
])
def test_feed_base_accepts_a_slug_or_a_career_host(entry, base):
    """Issue #227: a custom career host (CNAME to Teamtailor) works like a slug."""
    assert teamtailor._feed_base(entry) == base


def test_parse_rss_maps_items_like_the_json_feed():
    from paths import TESTS_DIR

    rss = (TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "teamtailor" / "jobs_templafy.rss").read_text(encoding="utf-8")
    company, items = teamtailor._parse_rss(rss)
    assert company == "Templafy"
    assert len(items) == 2
    first = items[0]
    assert first["title"] == "Maternity Cover: Brand & Motion Designer"
    assert first["platform_id"] == "8483649"
    assert first["url"] == "https://templafy.teamtailor.com/jobs/8483649-maternity-cover-brand-motion-designer"
    assert first["location"] == "København, Denmark"
    assert first["posted_at"].startswith("2026-10-01")
    assert "Templafy is seeking a Brand" in first["description"]

# --- feed detection (issue #282) ---

def _d(det):
    return None if det is None else (det.platform, det.entry)


def test_detect_url():
    assert _d(teamtailor.detect_url("https://templafy.teamtailor.com/jobs/8483649-designer")) == ("teamtailor", "templafy")
    assert teamtailor.detect_url("https://www.teamtailor.com/en/") is None
    assert teamtailor.detect_url("https://careers.teamtailor.com/x") is None


def test_detect_cname_and_html():
    assert _d(teamtailor.detect_cname("careers.veo.co", "ext.teamtailor.com", "w")) == ("teamtailor", "careers.veo.co")
    assert teamtailor.detect_cname("careers.veo.co", "acme.github.io", "w") is None
    html = '<link href="https://assets.teamtailor-cdn.com/assets/careersite.css">'
    assert _d(teamtailor.detect_html(html, "https://careers.veo.co/")) == ("teamtailor", "careers.veo.co")
    assert teamtailor.detect_html("<p>x</p>", "https://careers.veo.co/") is None


def test_the_feed_of_an_entry_is_its_jobs_json():
    assert teamtailor.feed_url("templafy") == "https://templafy.teamtailor.com/jobs.json"
    assert teamtailor.feed_url("careers.veo.co") == "https://careers.veo.co/jobs.json"
    assert teamtailor.FEED_KEY == "items"
    (probe,) = teamtailor.name_probes("acme")
    assert (probe.url, probe.key) == ("https://acme.teamtailor.com/jobs.json", "items")
