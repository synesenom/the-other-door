"""Unit tests for the pure helpers of the Choisir le service public scraper (choisirleservicepublic.gouv.fr)."""

from datetime import datetime
from pathlib import Path

import pytest

from door.scrapers.boards import choisirleservicepublic as csp

_FIX = Path(__file__).parent / "fixtures" / "choisirleservicepublic"
_BASE = "https://choisirleservicepublic.gouv.fr/nos-offres/filtres"


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


# --- location ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("location,code", [
    ("Paris", "208"), ("Paris, France", "208"), ("La Défense", "208"), ("Boulogne-Billancourt", "208"),
    ("Lyon", "336"), ("Toulouse", "305"), ("Marseille", "326"), ("Lille", "310"), ("Bordeaux", "239"),
    ("Nantes", "312"), ("Nice", "325"), ("Strasbourg", "236"), ("Rennes", "256"), ("Grenoble", "334"),
    ("Montpellier", "292"),
])
def test_a_city_maps_to_its_region_or_department_id(location, code):
    assert csp._location_id(location) == code


@pytest.mark.parametrize("location", ["", "France", "Remote", "Copenhagen", "Quimper", None])
def test_an_unknown_place_searches_the_whole_country(location):
    assert csp._location_id(location) is None


# --- urls -------------------------------------------------------------------------------------------

def test_search_url_is_a_path_of_filters_and_a_page():
    assert csp._search_url("data scientist", "208", 1) == f"{_BASE}/mot-cles/data%20scientist/localisation/208/"
    assert csp._search_url("data scientist", "208", 2) == f"{_BASE}/mot-cles/data%20scientist/localisation/208/page/2/"
    assert csp._search_url("comptable", None, 3) == f"{_BASE}/mot-cles/comptable/page/3/"


def test_search_url_encodes_the_keyword_as_a_path_segment():
    assert csp._search_url("chargé d'études/data", None, 1) == f"{_BASE}/mot-cles/charg%C3%A9%20d%27%C3%A9tudes%2Fdata/"


@pytest.mark.parametrize("url,ref", [
    ("https://choisirleservicepublic.gouv.fr/offre-emploi/data-scientist-confirmee-reference-2026-2452785/", "2026-2452785"),
    ("https://choisirleservicepublic.gouv.fr/offre-emploi/x-reference-MEF_2026-33266/", "MEF_2026-33266"),
    ("https://choisirleservicepublic.gouv.fr/offre-emploi/agent-reference-O062261027000403", "O062261027000403"),
])
def test_the_platform_id_is_the_reference_in_the_ad_link(url, ref):
    assert csp._platform_id(url) == ref


def test_a_link_without_a_reference_has_no_platform_id():
    assert csp._platform_id("https://choisirleservicepublic.gouv.fr/metiers/numerique/") is None


# --- dates ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,date", [
    ("En ligne depuis le 25 octobre 2026", datetime(2026, 10, 25)),
    ("En ligne depuis le 01 février 2026", datetime(2026, 2, 1)),
    ("En ligne depuis le 1er août 2026", datetime(2026, 8, 1)),
    ("En ligne depuis le 30 décembre 2025", datetime(2025, 12, 30)),
    ("28/09/2026", datetime(2026, 9, 28)),
])
def test_dates_in_french_or_numeric_form(text, date):
    assert csp._parse_date(text) == date


@pytest.mark.parametrize("text", ["", None, "En ligne depuis le 31 smarch 2026", "bientôt", "32/13/2026"])
def test_an_unreadable_date_is_none(text):
    assert csp._parse_date(text) is None


# --- search page ------------------------------------------------------------------------------------

def test_cards_carry_title_link_employer_place_and_date():
    cards = csp._parse_cards(_html("search_page1.html"))
    assert [c["id"] for c in cards] == ["2026-2452785", "MEF_2026-33266", "2026-2426235"]
    first = cards[0]
    assert first["title"] == "Data Scientist confirmé(e)"
    assert first["url"] == "https://choisirleservicepublic.gouv.fr/offre-emploi/data-scientist-confirmee-reference-2026-2452785/"
    assert first["company"] == "DSJ-SD - CCAS-Greffe"
    assert first["location"] == "Paris (75)"
    assert first["published"] == "En ligne depuis le 27 octobre 2026"
    assert cards[1]["location"] == "Val de Marne (94)"
    assert cards[1]["company"] == "Direction nationale du renseignement et des enquêtes douanières (DNRED)"


def test_cards_of_an_english_ad_are_read_the_same_way():
    titles = [c["title"] for c in csp._parse_cards(_html("search_english.html"))]
    assert titles[0] == "GRANT DESK COORDINATOR (Engage.Eu)"
    assert len(titles) == 2


def test_an_empty_result_page_has_no_cards():
    assert csp._parse_cards(_html("search_empty.html")) == []
    assert csp._parse_cards("") == []


def test_next_link_marks_a_page_with_more():
    assert csp._has_next(_html("search_page1.html")) is True
    assert csp._has_next(_html("search_page2.html")) is False
    assert csp._has_next("") is False


def test_a_result_page_or_the_empty_answer_is_a_results_page():
    assert csp._is_results_page(_html("search_page1.html")) is True
    assert csp._is_results_page(_html("search_empty.html")) is True
    assert csp._is_results_page("<html><body>Page introuvable</body></html>") is False
    assert csp._is_results_page("") is False


# --- detail page ------------------------------------------------------------------------------------

def test_detail_description_is_the_ad_text_with_its_headings_and_no_chrome():
    d = csp._parse_detail(_html("detail/2026-2452785.html"))
    text = d["description"]
    assert text.startswith("Vos missions en quelques mots\n")
    assert "Profil recherché" in text and "Compétences attendues" in text
    assert "Python, SQL" in text
    assert "Afficher la suite" not in text           # the clamp button is not the ad
    assert "Éléments de candidature" not in text      # nor the application block
    assert "<" not in text


def test_detail_company_and_place_come_from_the_page():
    d = csp._parse_detail(_html("detail/MEF_2026-33266.html"))
    assert d["company"] == "Direction nationale du renseignement et des enquêtes douanières (DNRED)"
    assert d["location"] == "Val de Marne (94), France"


def test_detail_falls_back_to_the_json_ld_description():
    page = ('<html><head><script type="application/ld+json">{"@type":"JobPosting","hiringOrganization":"Mairie X",'
            '"Description":"\\nVotre rôle : piloter le projet.Vos missions : suivre le budget."}</script></head><body></body></html>')
    d = csp._parse_detail(page)
    assert d["description"] == "Votre rôle : piloter le projet.Vos missions : suivre le budget."
    assert d["company"] == "Mairie X"


@pytest.mark.parametrize("page", ["", "<html><body><p>Offre expirée</p></body></html>", "<html><head><script type=\"application/ld+json\">not json</script></head></html>"])
def test_a_page_without_ad_text_has_no_detail(page):
    assert csp._parse_detail(page) is None


def test_card_posting_uses_the_card_alone():
    card = csp._parse_cards(_html("search_page1.html"))[0]
    p = csp._card_posting(card, datetime(2026, 10, 31))
    assert p["id"] == "choisirleservicepublic.2026-2452785"
    assert p["company"] == "DSJ-SD - CCAS-Greffe"
    assert p["posted_at"].startswith("2026-10-27")
    assert p["description"]


# --- local authorities --------------------------------------------------------------------------------

@pytest.mark.parametrize("pid,title,employer,company", [
    ("O069261020000123", "CHARGÉ D'ÉTUDES DONNÉES SIG (F/H) - SYTRAL MOBILITES", "Etablissements publics locaux", "SYTRAL MOBILITES"),
    ("O069261021000456", "Chargé d'études agriculture et PENAP - CONSEIL DÉPARTEMENTAL DU RHÔNE", "Conseils départementaux", "CONSEIL DÉPARTEMENTAL DU RHÔNE"),
    ("O069261021000789", "Chargé d'études agriculture", "Conseils départementaux", "Conseils départementaux"),
    ("2026-2452785", "Data Scientist - Chef de projet statistiques", "DSJ-SD - CCAS-Greffe", "DSJ-SD - CCAS-Greffe"),
])
def test_a_local_authority_ad_is_named_by_the_suffix_of_its_title(pid, title, employer, company):
    # The site files these under a category ("Communes", "Conseils départementaux"); the town or body is the title's last " - " part.
    assert csp._company(pid, title, employer) == company
