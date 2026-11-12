"""Unit tests for the pure helpers of the France Travail scraper (candidat.francetravail.fr)."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from door.scrapers.boards import francetravail

_FIX = Path(__file__).parent / "fixtures" / "francetravail"
_TODAY = datetime(2026, 10, 31)


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


# --- location ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("location,code", [
    ("Paris", "75056"), ("Paris, France", "75056"), ("paris", "75056"),
    ("Lyon", "69123"), ("Toulouse", "31555"), ("Marseille", "13055"), ("Lille", "59350"),
    ("Bordeaux", "33063"), ("Nantes", "44109"), ("Nice", "06088"), ("Strasbourg", "67482"),
    ("Rennes", "35238"), ("Grenoble", "38185"), ("Montpellier", "34172"),
    ("La Défense", "75056"), ("Boulogne-Billancourt", "75056"),
])
def test_a_city_maps_to_its_insee_commune_code(location, code):
    assert francetravail._insee_code(location) == code


@pytest.mark.parametrize("location", ["", "France", "Remote", "Copenhagen", "Quimper", None])
def test_an_unknown_place_searches_the_whole_country(location):
    assert francetravail._insee_code(location) is None


# --- freshness --------------------------------------------------------------------------------------

@pytest.mark.parametrize("days,emission", [(1, 1), (2, 3), (3, 3), (4, 7), (7, 7), (8, 14), (14, 14), (15, 31), (31, 31), (60, 31)])
def test_since_maps_to_the_smallest_emission_that_covers_it(days, emission):
    now = datetime(2026, 10, 31, 12)
    assert francetravail._emission_days(now - timedelta(days=days), now) == emission


def test_without_a_cutoff_the_search_covers_a_month():
    # Always sent: a keyword that is a known job title is redirected, losing its page and partner ads, without it.
    assert francetravail._emission_days(None, _TODAY) == 31


# --- urls -------------------------------------------------------------------------------------------

def test_search_url_carries_keyword_place_partner_ads_radius_order_and_emission():
    url = francetravail._search_url("chef de projet", "75056", 7, 1)
    assert url == ("https://candidat.francetravail.fr/offres/recherche?motsCles=chef+de+projet&lieux=75056"
                   "&offresPartenaires=true&rayon=10&tri=1&emission=7")


def test_search_url_pages_by_range_of_twenty():
    assert francetravail._search_url("comptable", "69123", 31, 2).endswith("&emission=31&range=20-39")
    assert francetravail._search_url("comptable", "69123", 31, 3).endswith("&range=40-59")


def test_search_url_without_a_place_has_no_lieux():
    url = francetravail._search_url("comptable", None, 31, 1)
    assert "lieux" not in url and "rayon" not in url and "motsCles=comptable" in url


def test_ad_and_detail_urls():
    assert francetravail._ad_url("8441867") == "https://candidat.francetravail.fr/offres/recherche/detail/8441867"
    assert francetravail._detail_url("215WLWF") == "https://candidat.francetravail.fr/api-descriptifoffre/offre/215WLWF"


# --- dates ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Publié aujourd'hui", datetime(2026, 10, 31)),
    ("Publié aujourd’hui", datetime(2026, 10, 31)),
    ("Publié hier", datetime(2026, 10, 30)),
    ("Publié il y a 1 jour", datetime(2026, 10, 30)),
    ("Publié il y a 2 jours", datetime(2026, 10, 29)),
    ("Publié il y a 12 jours", datetime(2026, 10, 19)),
    ("Publié le 12 octobre 2026", datetime(2026, 10, 12)),
    ("Publié le 3 février 2026", datetime(2026, 2, 3)),
    ("Publié le 05/10/2026", datetime(2026, 10, 5)),
])
def test_published_text_becomes_a_date(text, expected):
    assert francetravail._parse_published(text, _TODAY) == expected


@pytest.mark.parametrize("text", ["", None, "Publié récemment", "bientôt"])
def test_an_unreadable_published_text_is_none(text):
    assert francetravail._parse_published(text, _TODAY) is None


# --- search page ------------------------------------------------------------------------------------

def test_cards_are_read_from_a_search_page():
    cards = francetravail._parse_cards(_html("search_page1.html"))
    assert [c["id"] for c in cards] == ["8441867", "8441811", "8433015", "8450510"]
    first = cards[0]
    assert first["title"] == "Chef de Projet Si - MOE - Paiements H/F"
    assert first["company"] == "HN Services"
    assert first["location"] == "75 - Paris 1er Arrondissement"
    assert first["origin"] == "HELLOWORK"
    assert first["published"] == "Publié aujourd'hui"
    assert first["url"] == "https://candidat.francetravail.fr/offres/recherche/detail/8441867"
    assert first["teaser"].startswith("POSTE : Chef de Projet Si")


def test_an_ad_without_an_employer_has_an_empty_company():
    card = {c["id"]: c for c in francetravail._parse_cards(_html("search_page1.html"))}["8433015"]
    assert card["company"] == ""
    assert card["location"] == "75 - Paris 19e Arrondissement"


def test_alphanumeric_ids_of_direct_ads_and_their_origin():
    card = {c["id"]: c for c in francetravail._parse_cards(_html("search_page3.html"))}["215WLWF"]
    assert card["origin"] == "France Travail"
    assert card["company"] == "NRJ GROUP"
    assert card["published"] == "Publié hier"


def test_next_page_link_is_what_continues_a_keyword():
    assert francetravail._has_more(_html("search_page1.html")) is True
    assert francetravail._has_more(_html("search_short.html")) is False
    assert francetravail._has_more(_html("search_empty.html")) is False


def test_results_page_recognises_a_list_and_the_no_offers_answer():
    assert francetravail._is_results_page(_html("search_page1.html")) is True
    assert francetravail._is_results_page(_html("search_empty.html")) is True
    assert francetravail._is_results_page("<html><body><p>Maintenance</p></body></html>") is False
    assert francetravail._is_results_page("") is False


# --- detail -----------------------------------------------------------------------------------------

def test_detail_json_gives_the_description_and_the_employer():
    detail = francetravail._parse_detail((_FIX / "detail" / "8441867.json").read_text(encoding="utf-8"))
    assert detail["description"].startswith("POSTE : Chef de Projet Si - MOE - Paiements H/F")
    assert detail["company"] == "HN Services"
    assert detail["location"] == "75 - Paris 1er Arrondissement"
    assert "<" not in detail["description"]


def test_an_anonymous_ad_has_no_company():
    detail = francetravail._parse_detail((_FIX / "detail" / "8433015.json").read_text(encoding="utf-8"))
    assert detail["company"] == ""


def test_the_company_blurb_is_appended_to_the_description():
    detail = francetravail._parse_detail((_FIX / "detail" / "8296119.json").read_text(encoding="utf-8"))
    assert "Collective.work est une entreprise" in detail["description"]


@pytest.mark.parametrize("body", ["", "not json", "[]", "{}", '{"descriptif": ""}', '{"descriptif": null}'])
def test_a_detail_without_a_description_is_none(body):
    assert francetravail._parse_detail(body) is None
