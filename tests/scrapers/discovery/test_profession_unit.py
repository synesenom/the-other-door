"""Pure helpers of profession.hu employer discovery (`door.scrapers.discovery.profession`): the search URL, the
card parser and the grouping by employer. The pages are synthetic result pages in the
site's shape, a few made-up cards each (fixtures/profession/)."""

from pathlib import Path
from urllib.parse import unquote, urlparse

from door.scrapers.discovery import profession

_FIX = Path(__file__).parent / "fixtures" / "profession"


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


def _by_id(cards):
    return {c["platform_id"]: c for c in cards}


def test_the_source_contract_names():
    assert (profession.NAME, profession.COUNTRIES, profession.CONFIG_KEY) == ("profession", ("hu",), "profession_discovery")


def test_the_search_url_quotes_the_keyword_and_numbers_the_page():
    assert profession._search_url("data scientist", 1) == "https://www.profession.hu/allasok/1,0,0,data%20scientist"
    url = profession._search_url("adatelemző", 2)
    assert url.startswith("https://www.profession.hu/allasok/2,0,0,") and "%C5%91" in url
    assert unquote(urlparse(url).path).endswith(",adatelemző")


def test_a_card_gives_id_title_company_location_and_a_link_without_its_query():
    cards = _by_id(profession._parse_cards(_fx("search_data_scientist_p1.html")))
    assert len(cards) == 4
    card = cards["9000002"]
    assert card == {
        "platform_id": "9000002", "title": "Data Scientist (Medior)", "company": "GLOBEX ONLINE Zrt.",
        "location": "Budapest IX.kerület",
        "url": "https://www.profession.hu/allas/data-scientist-medior-globex-online-zrt-9000002",
    }
    assert "?" not in card["url"] and "hash" not in card["url"]


def test_a_card_with_a_work_mode_but_no_place_has_an_empty_location():
    cards = _by_id(profession._parse_cards(_fx("search_data_scientist_p1.html")))
    assert cards["9000001"]["location"] == "" and cards["9000001"]["company"] == "Acme Biztosító Zrt."
    assert cards["9000003"]["location"] == "Távmunka / Remote"


def test_a_card_without_a_location_element_has_an_empty_one():
    cards = _by_id(profession._parse_cards(_fx("search_data_scientist_p2.html")))
    assert cards["9000014"]["location"] == ""


def test_nested_elements_repeating_the_item_attributes_give_one_card_each():
    cards = profession._parse_cards(_fx("search_adatelemzo_hu.html"))
    assert [c["platform_id"] for c in cards] == ["9000021", "9000022", "9000023", "9000024", "9000001", "9000025"]


def test_hungarian_titles_keep_their_accents():
    cards = _by_id(profession._parse_cards(_fx("search_adatelemzo_hu.html")))
    assert cards["9000021"]["title"] == "Adatelemző szakértő"
    assert cards["9000022"]["company"] == "Kék Duna Nonprofit Zrt." and cards["9000022"]["location"] == "Budapest XII.kerület"


def test_a_duplicate_id_counts_once_and_a_card_missing_its_id_title_or_company_is_skipped():
    def li(i, name, brand):
        return (f'<li class="advertisement-result-list-item" data-item-id="{i}" data-item-name="{name}" '
                f'data-item-brand="{brand}" data-link="https://www.profession.hu/allas/x-{i}?k=1"></li>')
    html = "<ul>" + li("1", "Data Scientist", "A Kft.") + li("1", "Data Scientist", "A Kft.") + li("", "T", "B") \
        + li("3", "", "C") + li("4", "T", "") + "<li>plain</li></ul>"
    assert [c["platform_id"] for c in profession._parse_cards(html)] == ["1"]


def _card(i, title, company):
    return {"platform_id": str(i), "title": title, "company": company, "location": "Budapest",
            "url": f"https://www.profession.hu/allas/x-{i}"}


def test_only_on_topic_titles_are_kept_and_grouped_by_employer_in_order_of_first_sight():
    config = {"search_keywords": ["data scientist"], "location": "Budapest"}
    cards = [_card(1, "Senior Data Scientist", "Globex Zrt."), _card(2, "Demand planner", "Vortex Kft."),
             _card(3, "Data Scientist (Medior)", "GLOBEX ZRT."), _card(4, "Quality manager", "Soylent Kft."),
             _card(5, "Data Scientist", "Alfa Kft.")]
    got = profession._employers(cards, config)
    assert [e["company"] for e in got] == ["Globex Zrt.", "Alfa Kft."]
    assert got[0]["titles"] == ["Senior Data Scientist", "Data Scientist (Medior)"]
    assert got[0]["links"] == ["https://www.profession.hu/allas/x-1", "https://www.profession.hu/allas/x-3"]
    assert got[0]["job_ids"] == [] and got[0]["detailed"] is False


def test_hungarian_keywords_keep_hungarian_titles_and_drop_the_rest():
    config = {"search_keywords": ["adatelemző"], "location": "Budapest"}
    cards = profession._parse_cards(_fx("search_adatelemzo_hu.html"))
    got = {e["company"] for e in profession._employers(cards, config)}
    assert {"Példavárosi Tudományegyetem", "Kék Duna Nonprofit Zrt."} <= got
    assert "Vortex Ingredients Kft." not in got and "Soylent Magyarország Kft." not in got


def test_two_forms_of_one_employers_name_are_one_employer():
    config = {"search_keywords": ["data scientist"], "location": "Budapest"}
    cards = [_card(1, "Data Scientist", "Globex Online Zrt."), _card(2, "Data Scientist", "GLOBEX ONLINE")]
    assert len(profession._employers(cards, config)) == 1


def test_a_profession_ad_link_is_a_job_board_link_not_an_employer_site():
    from door.core import ats_detect

    assert ats_detect.is_job_board("https://www.profession.hu/allas/data-scientist-1234567")
    assert not ats_detect.is_job_board("https://karrier.example.hu/jobs/1")
