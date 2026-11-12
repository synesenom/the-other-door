"""Pure helpers of the ReliefWeb scraper: the RSS items, the country tag, the home-based marker."""

from pathlib import Path

from door.scrapers.boards import reliefweb

_FIX = Path(__file__).parent / "fixtures" / "reliefweb"


def _items():
    return reliefweb._parse_feed((_FIX / "mel_page.xml").read_text(encoding="utf-8"))


def test_the_feed_url_carries_the_keyword():
    assert reliefweb._feed_url("monitoring evaluation") == "https://reliefweb.int/jobs/rss.xml?search=monitoring+evaluation"


def test_an_item_is_read_into_its_fields():
    first = _items()[0]
    assert first["platform_id"] == "4236426"
    assert first["title"].startswith("Monitoring, Evaluation, Accountability and Learning (MEAL) Officer")
    assert first["company"] == "Project HOPE"
    assert first["countries"] == ["Nepal"]
    assert first["url"] == "https://reliefweb.int/job/4236426/meal-officer-nepal"
    assert first["posted_at"].isoformat() == "2026-10-30T17:30:03+00:00"
    assert "emergency response" in first["description"] and "<" not in first["description"]
    assert "Country:" not in first["description"] and "Organization:" not in first["description"]


def test_several_countries_and_none():
    by_id = {i["platform_id"]: i for i in _items()}
    assert by_id["4235700"]["countries"] == ["Germany", "Jordan", "Lebanon"]
    assert by_id["4235500"]["countries"] == []
    assert by_id["4235500"]["company"] == "Médecins du Monde - Belgique"


def test_the_location_is_the_tagged_countries():
    assert reliefweb._location_text(["Nepal"], False) == "Nepal"
    assert reliefweb._location_text(["Germany", "Jordan"], False) == "Germany, Jordan"
    assert reliefweb._location_text([], False) == ""


def test_a_home_based_job_says_so_and_names_its_country():
    assert reliefweb._location_text([], True) == "Home-based"
    assert reliefweb._location_text(["Kenya"], True) == "Home-based, Kenya"


def test_home_based_is_read_from_title_or_the_start_of_the_body():
    assert reliefweb._is_home_based("Consultant (home-based)", "")
    assert reliefweb._is_home_based("Consultant", "This work is Home based, with a trip.")
    assert not reliefweb._is_home_based("Consultant", "Based in the field office in Nairobi.")
    assert not reliefweb._is_home_based("Consultant", "x" * 3000 + " home-based")


def test_a_malformed_feed_is_an_error_not_an_empty_page():
    import pytest
    with pytest.raises(ValueError):
        reliefweb._parse_feed("<html>not a feed</html>")
