"""Pure helpers of the Arbetsförmedlingen (Platsbanken) scraper: the JobSearch answer, a hit's fields, the
location text, dates, and the municipality filter taken from the profile's location."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from door.scrapers.boards import arbetsformedlingen as af

_FIX = Path(__file__).parent / "fixtures" / "arbetsformedlingen"


def _page(name="search_page1.json") -> str:
    return (_FIX / name).read_text(encoding="utf-8")


def test_the_answer_is_read_into_hits_and_a_total():
    hits, total = af._parse_response(_page())
    assert total == 7 and [h["id"] for h in hits] == ["31668014", "31666374", "31632735", "31632254"]


@pytest.mark.parametrize("text", ["<html>maintenance</html>", "[]", '{"detail": "error"}', '{"hits": "x"}'])
def test_an_answer_without_a_hit_list_is_an_error(text):
    with pytest.raises(ValueError):
        af._parse_response(text)


def test_an_empty_answer_has_no_hits():
    assert af._parse_response(json.dumps({"total": {"value": 0}, "hits": []})) == ([], 0)


def test_a_hit_maps_to_a_posting():
    hit = af._parse_response(_page())[0][1]
    posting = af._to_posting(hit, datetime(2026, 10, 31, tzinfo=timezone.utc))
    assert posting["id"] == "arbetsformedlingen.31666374" and posting["platform_id"] == "31666374"
    assert posting["source"] == "arbetsformedlingen"
    assert posting["title"] == "Project Manager" and posting["company"] == "Schneider Electric Sverige AB"
    assert posting["url"] == "https://arbetsformedlingen.se/platsbanken/annonser/31666374"
    assert posting["location"] == "Stockholm"
    assert posting["description"].startswith("Project Manager, Sweden")
    assert posting["posted_at"].startswith("2026-10-30T11:50:04")  # 12:50 in Stockholm (CET after 25 Oct) is 11:50 UTC


def test_the_title_is_trimmed():
    assert af._to_posting({"id": "1", "headline": "  SAP AMS Project Manager  ", "employer": {"name": "X"}},
                          datetime.now(timezone.utc))["title"] == "SAP AMS Project Manager"


def test_a_hit_without_an_id_is_skipped():
    assert af._to_posting({"headline": "x"}, datetime.now(timezone.utc)) is None


def test_the_location_is_the_municipality_once_per_place():
    one = {"workplace_address": {"municipality": "Stockholm", "city": "STOCKHOLM"}}
    assert af._location_text(one) == "Stockholm"
    several = {"workplace_addresses": [{"municipality": "Stockholm"}, {"municipality": "Solna"}, {"municipality": "Stockholm"}]}
    assert af._location_text(several) == "Stockholm, Solna"


def test_the_location_falls_back_to_city_region_and_nothing():
    assert af._location_text({"workplace_address": {"municipality": None, "city": "Kista", "region": "Stockholms län"}}) == "Kista"
    assert af._location_text({"workplace_address": {"region": "Stockholms län"}}) == "Stockholms län"
    assert af._location_text({}) == ""


def test_remote_work_is_named_in_the_location():
    remote = {"workplace_model": {"label": "Distansarbete"}, "workplace_address": {"municipality": "Malmö"}}
    assert af._location_text(remote) == "Remote, Malmö"
    assert af._location_text({"workplace_model": {"label": "Arbete på plats"}, "workplace_address": {"municipality": "Malmö"}}) == "Malmö"
    assert af._location_text({"workplace_model": {"label": "Distansarbete"}}) == "Remote"


def test_dates_are_stockholm_local_time():
    assert af._parse_date("2026-01-15T09:00:00") == datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)
    assert af._parse_date("2026-07-15T09:00:00") == datetime(2026, 7, 15, 7, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("raw", [None, "", "yesterday", 5])
def test_an_unreadable_date_is_none(raw):
    assert af._parse_date(raw) is None


def test_a_removed_hit_is_dropped():
    assert af._is_live({"id": "1", "removed": False}) and not af._is_live({"id": "1", "removed": True})


def test_the_profile_city_selects_its_municipality_and_the_commute_area():
    ids = af._municipalities({"location": "Stockholm, Sweden"})
    assert ids[0] == "AvNB_uwa_6n6"                     # Stockholm first
    assert "zHxw_uJZ_NJ8" in ids and len(ids) == len(set(ids))   # Solna, no repeat
    assert af._municipalities({"location": "Göteborg"})[0] == "PVZL_BQT_XtL"
    assert af._municipalities({"location": "Gothenburg"})[0] == "PVZL_BQT_XtL"
    assert af._municipalities({"location": "Malmo"})[0] == "oYPt_yRA_Smm"


def test_an_unknown_place_searches_all_of_sweden():
    assert af._municipalities({"location": "Kiruna"}) == []
    assert af._municipalities({}) == []


def test_the_query_carries_keyword_municipalities_page_and_cutoff():
    params = af._params("project manager", ["AvNB_uwa_6n6", "zHxw_uJZ_NJ8"], 100, datetime(2026, 10, 28, 10, 30, tzinfo=timezone.utc))
    assert params["q"] == "project manager" and params["offset"] == 100 and params["limit"] == af._PAGE_SIZE
    assert params["municipality"] == ["AvNB_uwa_6n6", "zHxw_uJZ_NJ8"]
    assert params["sort"] == "pubdate-desc"
    assert params["published-after"] == "2026-10-28T11:30:00"   # the ads' own clock: Stockholm time (CET)
    bare = af._params("x", [], 0, None)
    assert "municipality" not in bare and "published-after" not in bare and bare["offset"] == 0


def test_the_cutoff_is_sent_in_stockholm_time_like_the_ads_dates():
    assert af._params("x", [], 0, datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc))["published-after"] == "2026-07-01T10:00:00"
