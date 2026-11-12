"""Pure helpers of HelloWork employer discovery (`door.scrapers.discovery.hellowork`): the search URL, the
card parser and the grouping by employer. The pages are synthetic result pages in the
site's shape, a few made-up cards each (fixtures/hellowork/)."""

from pathlib import Path

from door.scrapers.discovery import hellowork

_FIX = Path(__file__).parent / "fixtures" / "hellowork"


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


def _by_id(cards):
    return {c["platform_id"]: c for c in cards}


def test_the_source_contract_names():
    assert (hellowork.NAME, hellowork.COUNTRIES, hellowork.CONFIG_KEY) == ("hellowork", ("fr",), "hellowork_discovery")


def test_the_search_url_quotes_keyword_and_city_and_numbers_the_page_from_the_second():
    assert hellowork._search_url("chef de projet", "Paris", 1) == \
        "https://www.hellowork.com/fr-fr/emploi/recherche.html?k=chef+de+projet&l=Paris"
    url = hellowork._search_url("ingénieur données", hellowork._city("Paris, France"), 2)
    assert url == "https://www.hellowork.com/fr-fr/emploi/recherche.html?k=ing%C3%A9nieur+donn%C3%A9es&l=Paris&p=2"


def test_without_a_city_the_search_has_no_place():
    assert hellowork._search_url("data", "", 1).endswith("?k=data")


def test_a_card_gives_id_title_company_location_and_the_ad_link():
    cards = _by_id(hellowork._parse_cards(_fx("search_chef_de_projet_p1.html")))
    assert len(cards) == 5
    assert cards["90000002"] == {
        "platform_id": "90000002", "title": "Chef de Projet H/F", "company": "Groupe Imaginé",
        "location": "Paris - 75", "url": "https://www.hellowork.com/fr-fr/emplois/90000002.html",
    }
    assert cards["90000001"]["location"] == "Paris 2e - 75"


def test_accents_in_a_place_are_kept():
    cards = _by_id(hellowork._parse_cards(_fx("search_chef_de_projet_p1.html")))
    assert cards["90000004"]["location"] == "Île-de-France"
    assert cards["90000004"]["title"] == "Ingénieur Projet - Chef de Projet H/F"


def test_a_duplicate_id_counts_once_and_a_card_missing_its_id_title_or_company_is_skipped():
    def li(i, title, company):
        return (f'<li data-id-storage-item-id="{i}"><input type="hidden" name="title" value="{title}">'
                f'<input type="hidden" name="company" value="{company}">'
                f'<a data-cy="offerTitle" href="/fr-fr/emplois/{i or 9}.html?x=1"></a></li>')
    html = "<ul>" + li("1", "Chef de projet", "A SAS") + li("1", "Chef de projet", "A SAS") + li("", "T", "B") \
        + li("3", "", "C") + li("4", "T", "") + "<li>plain</li></ul>"
    cards = hellowork._parse_cards(html)
    assert [c["platform_id"] for c in cards] == ["1"] and cards[0]["location"] == ""
    assert cards[0]["url"] == "https://www.hellowork.com/fr-fr/emplois/1.html"


def test_a_card_without_its_hidden_inputs_falls_back_to_the_heading():
    html = ('<li data-id-storage-item-id="7"><a data-cy="offerTitle" href="/fr-fr/emplois/7.html"><h3>'
            '<span>Chef de projet H/F</span><span>Acme SAS</span></h3></a></li>')
    assert hellowork._parse_cards(html)[0]["company"] == "Acme SAS"


def _card(i, title, company):
    return {"platform_id": str(i), "title": title, "company": company, "location": "Paris - 75",
            "url": f"https://www.hellowork.com/fr-fr/emplois/{i}.html"}


def test_only_on_topic_titles_are_kept_and_grouped_by_employer_in_order_of_first_sight():
    config = {"search_keywords": ["chef de projet"], "location": "Paris"}
    cards = [_card(1, "Chef de Projet IA H/F", "Acme Groupe"), _card(2, "Boulanger H/F", "Maison Exemple"),
             _card(3, "Chef de Projet Risque H/F", "ACME GROUPE"), _card(4, "Comptable H/F", "Régie Exemple"),
             _card(5, "Chef de Projet H/F", "Alfa SAS")]
    got = hellowork._employers(cards, config)
    assert [e["company"] for e in got] == ["Acme Groupe", "Alfa SAS"]
    assert got[0]["titles"] == ["Chef de Projet IA H/F", "Chef de Projet Risque H/F"]
    assert got[0]["links"] == ["https://www.hellowork.com/fr-fr/emplois/1.html",
                               "https://www.hellowork.com/fr-fr/emplois/3.html"]
    assert got[0]["job_ids"] == [] and got[0]["detailed"] is False


def test_the_fixture_employers_are_the_on_topic_ones():
    config = {"search_keywords": ["chef de projet"], "location": "Paris"}
    cards = hellowork._parse_cards(_fx("search_chef_de_projet_p1.html")) + hellowork._parse_cards(_fx("search_chef_de_projet_p2.html"))
    got = {e["company"] for e in hellowork._employers(cards, config)}
    assert {"Acme Groupe", "Groupe Imaginé", "Hooli."} <= got


def test_a_hellowork_ad_link_is_a_job_board_link_not_an_employer_site():
    from door.core import ats_detect

    assert ats_detect.is_job_board("https://www.hellowork.com/fr-fr/emplois/90000002.html")
    assert not ats_detect.is_job_board("https://carrieres.example.fr/jobs/1")


def test_a_final_url_off_the_listing_is_a_wall():
    assert not hellowork._is_wall("https://www.hellowork.com/fr-fr/emploi/recherche.html?k=x&l=Paris")
    assert not hellowork._is_wall("https://www.hellowork.com/fr-fr/emplois/1.html")
    assert hellowork._is_wall("https://www.hellowork.com/fr-fr/candidat/connexion")
    assert hellowork._is_wall("https://elsewhere.example.com/fr-fr/emploi/recherche.html")
