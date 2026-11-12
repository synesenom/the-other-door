"""Unit tests for the pure helpers of the KÖZSZOLGÁLLÁS scraper (kozszolgallas.ksz.gov.hu)."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from door.scrapers.boards import kozigallas

_FIX = Path(__file__).parent / "fixtures" / "kozigallas"


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


# --- titles, dates ------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,title", [
    ("ápoló/szakápoló\n                            - 90/Szü/2026.\n", "ápoló/szakápoló"),
    ("Ápoló-gondozó (Darvastó)\n    -  9190", "Ápoló-gondozó (Darvastó)"),
    ("Szakápoló \n   - EPCHKHPO/9-166/2026", "Szakápoló"),
    ("Ápoló, szakápoló", "Ápoló, szakápoló"),
    ("Vezető ápoló (Sümeg-Nyírlakpuszta)\n      ", "Vezető ápoló (Sümeg-Nyírlakpuszta)"),
    ("Gyógyszerész - gyermek osztály", "Gyógyszerész - gyermek osztály"),  # a dash with no reference after it is part of the title
])
def test_the_institutions_reference_is_cut_from_the_title(raw, title):
    assert kozigallas._clean_title(raw) == title


@pytest.mark.parametrize("text,expected", [
    ("2026.11.11.", datetime(2026, 11, 11)),
    ("2026.12.03. 00:00", datetime(2026, 12, 3)),
    (" 2026. 11. 08. ", datetime(2026, 11, 8)),
    ("soon", None), ("", None), (None, None), ("2026.13.40.", None),
])
def test_parse_date_reads_the_portals_dotted_dates(text, expected):
    assert kozigallas._parse_date(text) == expected


# --- search request and page --------------------------------------------------------------------------

def test_the_search_body_names_keyword_page_and_size():
    body = json.loads(kozigallas._search_body("ápoló", 2))
    assert body == {"page": 2, "pagesize": kozigallas._PAGE_SIZE, "sort": "Created DESC", "keyword": "ápoló"}


def test_parse_cards_reads_id_title_employer_place_deadline_and_link():
    cards = kozigallas._parse_cards(_html("list_p1.html"))
    assert [c["id"] for c in cards] == ["175084", "175074", "175065"]
    first = cards[0]
    assert first["title"] == "ápoló/szakápoló"
    assert first["company"].startswith("SZOLNOKI KISTÉRSÉG")
    assert first["location"] == "Rákóczifalva"
    assert first["deadline"] == "2026.11.27."
    assert first["url"] == "https://kozszolgallas.ksz.gov.hu/JobAd/Info/175084"


def test_parse_cards_skips_a_card_without_title_and_reads_nothing_from_an_empty_page():
    assert kozigallas._parse_cards(_html("list_empty.html")) == []
    assert kozigallas._parse_cards('<div class="jobad jobaditemelement" id="9"></div>') == []
    assert kozigallas._parse_cards("") == []


def test_page_count_is_read_from_the_hidden_field():
    assert kozigallas._page_count(_html("list_p1.html")) == 2
    assert kozigallas._page_count(_html("list_empty.html")) == 0
    assert kozigallas._page_count("<html></html>") is None


def test_a_results_page_is_cards_or_the_answer_with_a_total():
    assert kozigallas._is_results_page(_html("list_p1.html"))
    assert kozigallas._is_results_page(_html("list_empty.html"))
    assert not kozigallas._is_results_page("<html><body>Hiba történt</body></html>")
    assert not kozigallas._is_results_page("")


def test_total_zero_is_a_no_hits_answer():
    assert kozigallas._no_hits(_html("list_empty.html"))
    assert not kozigallas._no_hits(_html("list_p1.html"))


# --- ad page ------------------------------------------------------------------------------------------

def test_parse_detail_reads_text_place_and_publication_date():
    detail = kozigallas._parse_detail(_html("detail_175084.html"))
    assert detail["location"] == "Rákóczifalva"
    assert detail["posted_at"] == datetime(2026, 11, 11)
    assert detail["deadline"] == datetime(2026, 11, 27)
    d = detail["description"]
    assert "Tevékenységi kör (ellátandó feladatok): Az ellátottak egészségi állapotának" in d
    assert "Elvárt végzettség/képesítés:" in d and "szakápoló" in d
    assert "<" not in d and "&nbsp;" not in d and "\xa0" not in d


def test_parse_detail_without_a_publication_date_has_none():
    detail = kozigallas._parse_detail(_html("detail_175065.html"))
    assert detail["posted_at"] is None
    assert detail["description"]


def test_parse_detail_of_a_page_without_the_ad_is_none():
    assert kozigallas._parse_detail("<html><body><p>Az álláshirdetés nem található.</p></body></html>") is None
    assert kozigallas._parse_detail("") is None
