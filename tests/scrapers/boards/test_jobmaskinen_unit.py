"""Unit tests for the pure helpers of the Jobmaskinen scraper (job.jobmaskinen.dk)."""

from datetime import datetime, timezone
from pathlib import Path

from door.scrapers.boards import jobmaskinen

_FIX = Path(__file__).parent / "fixtures" / "jobmaskinen"


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


def test_search_url_first_page_has_no_offset():
    # offset=0 is answered with a redirect that drops the query, so page 1 sends none.
    url = jobmaskinen._search_url("elektriker", 1)
    assert url == "https://job.jobmaskinen.dk/jobliste/?searchit=&searchjobtitel=elektriker&searchbeliggenhed="


def test_search_url_later_pages_step_the_offset_by_ten():
    assert jobmaskinen._search_url("el installatør", 3).endswith(
        "searchjobtitel=el+installat%C3%B8r&searchbeliggenhed=&offset=20")


def test_job_url_names_the_jobnet_id():
    assert jobmaskinen._job_url("6535427") == "https://job.jobmaskinen.dk/jobliste/?jobnet=6535427"


def test_parse_cards_reads_every_field_of_a_card():
    cards, has_next = jobmaskinen._parse_cards(_fx("search_page1.html"))
    assert has_next is True
    assert [c["platform_id"] for c in cards] == ["6535427", "6535434", "6535450"]
    first = cards[0]
    assert first["title"] == "Elektriker til el-installation i boliger og erhverv i Odense"
    assert first["company"] == "PowerMatch ApS"
    assert first["tag"] == "Elektriker"
    assert first["place"] == "Odense"
    assert first["posted_at"] == datetime(2026, 10, 29, tzinfo=timezone.utc)


def test_parse_cards_last_page_has_no_next():
    cards, has_next = jobmaskinen._parse_cards(_fx("search_last_page.html"))
    assert has_next is False
    assert [c["platform_id"] for c in cards] == ["6530742", "6529404"]
    assert cards[0]["company"] == "EUROFINS BIOPHARMA PRODUCT TESTINGDENMARK A/S"


def test_parse_cards_middle_page_has_next_after_a_previous_link():
    _, has_next = jobmaskinen._parse_cards(_fx("search_page2.html"))
    assert has_next is True


def test_parse_cards_without_results_is_empty():
    assert jobmaskinen._parse_cards("<html><body>nothing</body></html>") == ([], False)


def test_parse_card_date():
    assert jobmaskinen._parse_card_date("29-10-2026") == datetime(2026, 10, 29, tzinfo=timezone.utc)
    assert jobmaskinen._parse_card_date("") is None
    assert jobmaskinen._parse_card_date("i dag") is None


def test_parse_detail_reads_the_json_ld():
    detail = jobmaskinen._parse_detail(_fx("detail_6535427.html"))
    assert detail["title"].startswith("Elektriker til el-installation")
    assert detail["company"] == "PowerMatch ApS"
    assert detail["location"] == "Odense"
    assert detail["posted_at"] == "2026-10-29T12:33:53+01:00"
    assert "<" not in detail["description"]
    assert detail["description"].startswith("Kan du lide at arbejde selvstændigt")
    assert "Løn efter overenskomst" in detail["description"]


def test_parse_detail_without_json_ld_is_none():
    assert jobmaskinen._parse_detail("<html><body>Siden findes ikke</body></html>") is None


def test_parse_detail_ignores_other_ld_blocks():
    html = ('<script type="application/ld+json">{"@type":"WebPage"}</script>'
            '<script type="application/ld+json">not json</script>')
    assert jobmaskinen._parse_detail(html) is None


def test_mirror_hosts_are_job_boards():
    assert "jobmaskinen." in jobmaskinen.JOB_BOARD_HOSTS


def test_results_page_is_cards_or_the_no_match_marker():
    assert jobmaskinen._is_results_page(_fx("search_page1.html")) is True
    assert jobmaskinen._is_results_page(_fx("search_no_results.html")) is True


def test_results_page_is_not_an_unrecognised_page():
    assert jobmaskinen._is_results_page("<html><body>Ingen job</body></html>") is False
    # the container alone, with the cards renamed and no marker, is a changed site
    renamed = _fx("search_page1.html").replace("dbj_jobbox", "dbj_x").replace("dbj_jobHeadline", "dbj_y")
    assert jobmaskinen._is_results_page(renamed) is False
