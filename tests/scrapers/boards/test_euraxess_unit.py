"""Unit tests for EURAXESS's pure helpers (issue #431): saved pages, no network."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from door.scrapers.boards import euraxess

_FIX = Path(__file__).parent / "fixtures" / "euraxess"


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


def test_the_listing_params_filter_the_country_and_sort_newest_first():
    assert euraxess._params("dk", 0) == {"f[0]": "job_country:757", "sort[name]": "created", "sort[direction]": "DESC"}
    assert euraxess._params("fr", 0)["f[0]"] == "job_country:793"
    assert euraxess._params("se", 0)["f[0]"] == "job_country:770"
    assert euraxess._params("gb", 0)["f[0]"] == "job_country:771"
    assert euraxess._params("hu", 2)["f[0]"] == "job_country:748" and euraxess._params("hu", 2)["page"] == 2


def test_a_listing_page_gives_one_card_per_offer_and_whether_there_is_a_next_page():
    cards, has_next = euraxess.parse_listing(_html("search_dk_page1.html"))
    assert has_next is True
    assert [c["id"] for c in cards] == ["476999", "476522", "476205", "475660"]
    first = cards[0]
    assert first["title"] == "Postdoc in Quantum Optics"
    assert first["company"] == "University of Copenhagen"
    assert first["posted_at"] == datetime(2026, 10, 30, tzinfo=timezone.utc)
    assert first["url"] == "https://euraxess.ec.europa.eu/jobs/476999"
    assert first["research_field"] == "Physics" and first["profile"].startswith("Recognised Researcher")
    assert first["location"] == "Copenhagen, Denmark"
    assert first["teaser"].startswith("A postdoctoral position")
    assert euraxess.parse_listing(_html("search_dk_page2.html"))[1] is False


def test_a_page_without_offers_has_no_cards():
    assert euraxess.parse_listing("<html><body><p>No results have been found</p></body></html>") == ([], False)


@pytest.mark.parametrize("text, expected", [
    ("Number of offers: 1, Denmark, Geus, Aarhus, 8000, Universitetsbyen 81", "Aarhus, Denmark"),
    ("Number of offers: 2, Denmark, PhD-Jobs.NET", "Denmark"),
    ("Number of offers: 15, Denmark, DTU Electro, Paris, 75005, Rue X 1", "Denmark"),   # several posts, several places
    ("Number of offers: 1, Hungary, University of Szeged, Szeged, 6720, Dugonics tér 13", "Szeged, Hungary"),
    ("", ""),
])
def test_the_work_location_is_the_city_and_the_country(text, expected):
    assert euraxess._location(text) == expected


def test_the_offer_text_is_the_description_block_of_the_job_page():
    text = euraxess.parse_detail(_html("job_476999.html"))
    assert text.startswith("The Niels Bohr Institute invites applications")
    assert "trapped atoms" in text and "PhD in physics" in text
    assert "kontakt@example.com" not in text and "<" not in text
    assert euraxess.parse_detail("<p>nothing</p>") == ""


def test_an_offer_is_on_topic_by_its_title_its_research_field_or_its_teaser():
    terms = ["physics", "quantum"]
    card = {"title": "Postdoc", "research_field": "Physics", "teaser": ""}
    assert euraxess._relevant(card, terms)
    assert euraxess._relevant({"title": "Quantum engineer", "research_field": "", "teaser": ""}, terms)
    assert euraxess._relevant({"title": "Postdoc", "research_field": "", "teaser": "work on quantum sensors"}, terms)
    assert not euraxess._relevant({"title": "Plastic Surgeon", "research_field": "Medicine", "teaser": ""}, terms)
    assert euraxess._relevant({"title": "Plastic Surgeon", "research_field": "Medicine", "teaser": ""}, [])   # no terms: keep all


def test_the_served_countries_are_the_registered_ones_and_each_has_a_facet():
    from door.core import sites

    assert euraxess._SERVED == tuple(sites.SITES["euraxess"].countries) == tuple(euraxess._COUNTRY_FACETS)


@pytest.mark.parametrize("location, config, expected", [
    ("Denmark", "Copenhagen, Denmark", True),
    ("Copenhagen, Denmark", "Copenhagen, Denmark", True),
    ("Oslo, Norway", "Copenhagen, Denmark", False),
    ("Portugal", "Copenhagen, Denmark", False),
    ("Latvia", "Copenhagen, Denmark", False),
    ("Paris, France", "Paris, France", True),
    ("Denmark", "Paris, France", False),
    ("", "Copenhagen, Denmark", False),
])
def test_a_card_is_local_when_its_country_is_the_profiles(location, config, expected):
    assert euraxess._card_is_local({"location": location}, {"location": config}) is expected
