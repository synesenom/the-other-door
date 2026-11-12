"""Pure helpers of Jobbsafari employer discovery (`door.scrapers.discovery.jobbsafari`): the search URL, the
result parser, the apply-link cleaning and the grouping by employer. The pages are synthetic result pages
in the site's shape (``__NEXT_DATA__``), a few made-up results each (fixtures/jobbsafari/)."""

from pathlib import Path

from door.scrapers.discovery import jobbsafari

_FIX = Path(__file__).parent / "fixtures" / "jobbsafari"


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


def _by_id(cards):
    return {c["platform_id"]: c for c in cards}


def test_the_source_contract_names():
    assert (jobbsafari.NAME, jobbsafari.COUNTRIES, jobbsafari.CONFIG_KEY) == ("jobbsafari", ("se",), "jobbsafari_discovery")


def test_the_search_url_quotes_the_keyword_and_pages_from_the_second_page():
    assert jobbsafari._search_url("project manager", 1) == "https://jobbsafari.se/lediga-jobb?sok=project%20manager"
    assert jobbsafari._search_url("project manager", 2) == "https://jobbsafari.se/lediga-jobb?sok=project%20manager&page=2"
    assert "sok=systemutvecklare%20%C3%A5" in jobbsafari._search_url("systemutvecklare å", 1)


def test_a_result_gives_id_title_company_place_and_the_employers_apply_link_without_tracking():
    cards = _by_id(jobbsafari._parse_cards(_fx("search_project_manager_p1.html")))
    assert len(cards) == 6
    card = cards["30000001"]
    assert card["title"] == "Projektledare (erfaren) inom anläggning"
    assert card["company"] == "Exempelby Kommun" and card["location"] == "Exempelby"
    assert card["url"].startswith("https://recruit.example.com/spa/public/apply?guidAssignment=")
    assert "utm_" not in card["url"] and "publishCode=PB" in card["url"]
    assert set(card) == {"platform_id", "title", "company", "location", "url"}


def test_a_link_loses_only_its_tracking_parameters():
    clean = jobbsafari._clean_link
    assert clean("https://jobs.globex.example/x/1/?feedId=355&utm_source=jobbsafari.se&utm_medium=referral") == "https://jobs.globex.example/x/1/?feedId=355"
    assert clean("https://careers.initrode.example/job/1?_atxsrc=Example&utm_source=Example") == "https://careers.initrode.example/job/1"
    assert clean("https://www.initech.example/lediga-jobb/a?utm_source=jobbsafari.se#top") == "https://www.initech.example/lediga-jobb/a"


def test_an_email_application_or_a_non_web_link_gives_no_link():
    assert jobbsafari._clean_link("mailto:kontakt@example.com") == ""
    assert jobbsafari._clean_link("") == ""
    cards = _by_id(jobbsafari._parse_cards(_fx("search_project_manager_p2.html")))
    mail = next(c for c in cards.values() if c["company"] == "Vandelay Technologies Sweden AB")
    assert mail["url"] == ""


def test_a_page_without_results_or_without_the_data_block_gives_no_cards():
    assert jobbsafari._parse_cards(_fx("search_empty.html")) == []
    assert jobbsafari._parse_cards("<html><body>nothing</body></html>") == []
    assert jobbsafari._parse_cards('<script id="__NEXT_DATA__" type="application/json">not json</script>') == []


def test_a_duplicate_id_counts_once_and_a_result_missing_its_id_title_or_company_is_skipped():
    def entry(pk, title, company):
        return {"pk": pk, "title": title, "company": {"name": company}, "locations": [], "apply": {"method": "url", "href": "https://a.example.com/1"}}
    import json
    data = {"props": {"pageProps": {"jobEntries": {"results": [
        entry(1, "Project Manager", "A AB"), entry(1, "Project Manager", "A AB"), entry(None, "T", "B"),
        entry(3, "", "C"), entry(4, "T", ""), {"pk": 5, "title": "T", "company": None}]}}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    assert [c["platform_id"] for c in jobbsafari._parse_cards(html)] == ["1"]


def _card(i, title, company, url=None):
    return {"platform_id": str(i), "title": title, "company": company, "location": "Stockholm",
            "url": f"https://careers.example.com/job/{i}" if url is None else url}


def test_only_on_topic_titles_are_kept_and_grouped_by_employer_in_order_of_first_sight():
    config = {"search_keywords": ["project manager"], "location": "Stockholm"}
    cards = [_card(1, "Senior Project Manager", "Hooli AB"), _card(2, "Lagerarbetare", "Lager Exempel AB"),
             _card(3, "Project Manager", "HOOLI AB"), _card(4, "Kock", "Krog Exempel AB"), _card(5, "Project Manager", "Alfa AB", "")]
    got = jobbsafari._employers(cards, config)
    assert [e["company"] for e in got] == ["Hooli AB", "Alfa AB"]
    assert got[0]["titles"] == ["Senior Project Manager", "Project Manager"]
    assert got[0]["links"] == ["https://careers.example.com/job/1", "https://careers.example.com/job/3"]
    assert got[0]["job_ids"] == [] and got[0]["detailed"] is False
    assert got[1]["links"] == []


def test_swedish_keywords_keep_swedish_titles_and_drop_the_rest():
    config = {"search_keywords": ["projektledare"], "location": "Stockholm"}
    cards = jobbsafari._parse_cards(_fx("search_project_manager_p1.html"))
    got = {e["company"] for e in jobbsafari._employers(cards, config)}
    assert {"Exempelby Kommun", "Globex Energi", "Initrode Kraft"} <= got


def test_a_jobbsafari_link_is_a_job_board_link_not_an_employer_site():
    from door.core import ats_detect

    assert ats_detect.is_job_board("https://jobbsafari.se/jobb/projektledare-1234")
    assert not ats_detect.is_job_board("https://jobs.globex.example/job/1")


def test_the_wall_check():
    assert not jobbsafari._is_wall("https://jobbsafari.se/lediga-jobb?sok=x&page=2")
    assert jobbsafari._is_wall("https://jobbsafari.se/logga-in")
    assert jobbsafari._is_wall("https://elsewhere.example.com/lediga-jobb")
