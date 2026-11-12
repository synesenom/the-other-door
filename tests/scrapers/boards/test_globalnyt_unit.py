"""Pure helpers of the Globalnyt scraper: the ad list, the detail page's labelled fields."""

import json
from pathlib import Path

from door.scrapers.boards import globalnyt

_FIX = Path(__file__).parent / "fixtures" / "globalnyt"


def _ads():
    return globalnyt._parse_list(json.loads((_FIX / "stilling_list.json").read_text(encoding="utf-8")))


def test_an_ad_is_read_from_the_list():
    ad = _ads()[0]
    assert ad["platform_id"] == "510393" and ad["title"] == "MHPSS Advisor"
    assert ad["url"] == "https://globalnyt.dk/stilling/mhpss-advisor/"
    assert ad["posted_at"].isoformat() == "2026-10-27T09:12:50+00:00"
    assert "psychosocial" in ad["description"] and "<" not in ad["description"]


def test_html_entities_in_a_title_are_decoded():
    assert _ads()[1]["title"] == "Maternity cover: Partnership Manager for Oxfam Denmark’s international programme"
    assert _ads()[2]["title"] == "Head of Programmes – Ukraine"


def test_the_detail_page_names_organisation_deadline_and_place():
    html = (_FIX / "detail_mhpss.html").read_text(encoding="utf-8")
    assert globalnyt._detail_field(html, "Organisation") == "Røde Kors"
    assert globalnyt._detail_field(html, "Ansøgningsfrist") == "18/11/2026"
    assert globalnyt._detail_field(html, "Sted") == "København"


def test_a_missing_field_is_empty_and_a_menu_link_is_not_a_field():
    html = (_FIX / "detail_noorg.html").read_text(encoding="utf-8")
    assert globalnyt._detail_field(html, "Organisation") == ""
    assert globalnyt._detail_field((_FIX / "detail_oxfam.html").read_text(encoding="utf-8"), "Sted") == ""


def test_a_list_that_is_not_a_list_is_an_error():
    import pytest
    with pytest.raises(ValueError):
        globalnyt._parse_list({"code": "rest_no_route"})
