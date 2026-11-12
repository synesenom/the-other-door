"""Unit tests for the pure helpers of the Akademikernes Jobbank scraper (jobbank.dk)."""

from datetime import datetime
from pathlib import Path

import pytest

from door.scrapers.boards import jobbank

_FIX = Path(__file__).parent / "fixtures" / "jobbank"


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


def test_search_url_carries_the_keyword_and_page():
    assert jobbank._search_url("senior reward analyst", 2) == "https://jobbank.dk/job/?key=senior+reward+analyst&page=2"
    assert jobbank._search_url("økonomi", 1) == "https://jobbank.dk/job/?key=%C3%B8konomi&page=1"


def test_detail_url_is_the_ad_id():
    assert jobbank._detail_url("3119510") == "https://jobbank.dk/job/3119510/"


def test_cards_of_a_search_page():
    cards = jobbank._parse_cards(_html("search_page1.html"))
    assert len(cards) == 20
    nobia = cards[0]
    assert nobia["id"] == "3133352"
    assert nobia["title"] == "Compensation & Benefits Partner"
    assert nobia["company"] == "Nobia Denmark A/S"
    assert nobia["region"] == "Østjylland (Aarhus)"
    assert nobia["updated"] == datetime(2026, 10, 6)
    assert nobia["url"] == "https://jobbank.dk/job/3133352/"


def test_a_card_with_a_comma_free_company_and_two_regions():
    cards = {c["id"]: c for c in jobbank._parse_cards(_html("search_page1.html"))}
    assert cards["3125524"]["company"] == "Trustpilot A/S"
    assert cards["3125524"]["region"] == "Storkøbenhavn, Udlandet (øvrige)"
    # the company's trailing space before the comma is dropped
    assert cards["3147764"]["company"] == "VOI Denmark ApS"
    assert cards["3147764"]["region"] == "Udlandet (Sverige)"


def test_a_title_with_markup_in_its_header_is_plain_text():
    cards = {c["id"]: c for c in jobbank._parse_cards(_html("search_page2.html"))}
    assert cards["3123940"]["title"].startswith("Experienced Rewards Consultant")
    assert "<" not in cards["3123940"]["title"]
    assert cards["3123940"]["company"].startswith("PwC - Revision | Skat")


def test_an_empty_search_page_has_no_cards():
    assert jobbank._parse_cards(_html("search_empty.html")) == []
    assert jobbank._parse_cards("<html>nothing</html>") == []


@pytest.mark.parametrize("text, expected", [
    ("Fuldtidsjob hos Nobia Denmark A/S, Østjylland (Aarhus)", ("Nobia Denmark A/S", "Østjylland (Aarhus)")),
    ("Deltidsjob hos Coloplast, Nordsjælland", ("Coloplast", "Nordsjælland")),
    ("Fuldtidsjob hos Acme ApS", ("Acme ApS", "")),
    ("Something else", ("", "")),
])
def test_teaser(text, expected):
    assert jobbank._parse_teaser(text) == expected


def test_card_date():
    assert jobbank._parse_card_date("Opdateret: 06.10.2026") == datetime(2026, 10, 6)
    assert jobbank._parse_card_date("Opdateret: i dag") is None
    assert jobbank._parse_card_date("") is None


def test_detail_json_ld_english():
    d = jobbank._parse_detail(_html("detail_3119510.html"))
    assert d["title"] == "Total Rewards Senior Analyst"
    assert d["company"] == "Accenture"
    assert d["location"] == "København S"
    assert d["posted_at"] == datetime(2026, 9, 15)
    assert d["description"].startswith("About the role")
    assert "<" not in d["description"]


def test_detail_json_ld_danish_keeps_the_letters():
    d = jobbank._parse_detail(_html("detail_3146289.html"))
    assert d["company"] == "Forsvaret"
    assert d["location"] == "Hjørring"
    assert "søger en kollega" in d["description"]


def test_detail_without_a_location_has_none():
    assert jobbank._parse_detail(_html("detail_3147764.html"))["location"] == ""


def test_detail_without_json_ld_is_none():
    assert jobbank._parse_detail("<html><body>no data</body></html>") is None
    assert jobbank._parse_detail('<script type="application/ld+json">{not json</script>') is None
    assert jobbank._parse_detail('<script type="application/ld+json">{"@type": "Organization"}</script>') is None


@pytest.mark.parametrize("address, expected", [
    ({"addressLocality": "København S", "postalCode": "2300"}, "København S"),
    ({"addressLocality": "", "postalCode": ""}, ""),
    (None, ""),
    ("Aarhus", "Aarhus"),
])
def test_location_text(address, expected):
    assert jobbank._location_text(address) == expected


@pytest.mark.parametrize("body, status, expected", [
    ("<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/x'></script></html>", 200, True),
    ("<html>Attention Required! | Cloudflare</html>", 200, True),
    ("anything", 403, True),
    ("anything", 429, True),
    ("<html><body>ok</body></html>", 200, False),
])
def test_challenge_detection(body, status, expected):
    assert jobbank._is_challenge(body, status) is expected


def test_a_real_search_page_is_no_challenge():
    assert jobbank._is_challenge(_html("search_page1.html"), 200) is False
