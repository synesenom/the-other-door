"""Visma Recruit employers that list their ads on their own website (issue #567): the entry is the list page's
address, its ads are found there and read through Visma's public ad JSON. Real pages of Region Västerbotten,
Uppvidinge kommun, Uppsala kommun and Region Gävleborg, trimmed and rewritten."""

import json
from datetime import datetime

import pytest

from door.scrapers.feeds import visma_recruit as v
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "visma_recruit"


def _html(name):
    return (_FX / name).read_text(encoding="utf-8")


def _settings(guid):
    return json.loads((_FX / f"settings_{guid}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("value, expected", [
    ("https://www.uppsala.se/jobb/lediga-jobb/", "https://www.uppsala.se/jobb/lediga-jobb/"),
    ("https://www.uppsala.se:443/jobb/lediga-jobb/?page=2#js-vacancies-filter-results", "https://www.uppsala.se/jobb/lediga-jobb/?page=2"),
    ("  http://www.uppvidinge.se/a/b.html ", "http://www.uppvidinge.se/a/b.html"),
])
def test_an_employers_list_page_is_an_entry(value, expected):
    assert v.page_entry(value) == expected


@pytest.mark.parametrize("value", [
    "f636d73d-8356-43c6-99bd-ba01addf1b55", "nässjö", "",
    "https://recruit.visma.com/External/OJCustomer3/AssignmentList.aspx?guidExtSoftware=f636d73d-8356-43c6-99bd-ba01addf1b55",
    "https://recruit.visma.com/spa/public/apply?guidAssignment=7dfdb3da-5394-4919-9171-1bd50ffc3f8c",
    "mailto:hr@example.com",
])
def test_a_list_id_a_name_or_a_visma_link_is_no_list_page(value):
    assert v.page_entry(value) is None


def test_a_page_whose_ad_links_carry_the_visma_id_names_the_ads_directly():
    found = v.parse_page(_html("vasterbotten_list.html"), "https://www.regionvasterbotten.se/sok-jobb")
    assert found["guids"] == ["2dc1cf30-de83-4ee2-aa48-29457e86e557", "7c121586-df86-4e26-aa4c-a37efb90f6ad",
                              "54cb6759-74eb-415f-96e0-600ed6921971"]
    assert found["ads"] == [] and found["pages"] == []


def test_offentliga_jobb_ad_links_name_the_ad_by_remote_id():
    found = v.parse_page(_html("uppvidinge_list.html"), "https://www.uppvidinge.se/naringsliv-och-arbete/arbetsmarknad/lediga-jobb-i-kommunen.html")
    assert found["guids"] == ["984ec35e-aa56-416d-9415-805a95e47244", "27f683a8-4c5f-4420-b155-a61379984ba9",
                              "e94165db-d3a7-44c7-adfe-5604da06c244"]   # the PublisherGuid is not an ad


def test_ad_pages_under_the_list_and_the_paging_are_found_on_an_own_ad_list():
    found = v.parse_page(_html("uppsala_list_1.html"), "https://www.uppsala.se/jobb/lediga-jobb/")
    assert found["guids"] == []
    assert found["ads"] == ["https://www.uppsala.se/jobb/lediga-jobb/Details/?id=GSN-2026-01761",
                            "https://www.uppsala.se/jobb/lediga-jobb/Details/?id=UBN-2026-05557",
                            "https://www.uppsala.se/jobb/lediga-jobb/Details/?id=UBN-2026-05522"]
    assert found["pages"] == [f"https://www.uppsala.se/jobb/lediga-jobb/?page={n}" for n in (1, 2, 3, 4)]


def test_links_outside_the_list_are_no_ads():
    found = v.parse_page(_html("gavleborg_list.html"), "https://www.regiongavleborg.se/jobb-och-utbildning/lediga-jobb/")
    assert found["ads"] == [f"https://www.regiongavleborg.se/jobb-och-utbildning/lediga-jobb/{n}/" for n in (1457976, 1455047, 1457635)]
    html = '<a href="/om-oss/">Om oss</a><a href="/jobb/lediga-jobb/x/">x</a><a href="/jobb/lediga-jobb/y.pdf">y</a>'
    assert v.parse_page(html, "https://acme.se/")["ads"] == []   # a start page's every link is not an ad
    assert v.parse_page(html, "https://acme.se/jobb/lediga-jobb/")["ads"] == ["https://acme.se/jobb/lediga-jobb/x/"]


def test_the_visma_id_of_an_own_ad_page_is_its_apply_links():
    assert v.parse_apply_guid(_html("uppsala_ad_1_1.html")) == "7dfdb3da-5394-4919-9171-1bd50ffc3f8c"
    assert v.parse_apply_guid("<p>Ansök via e-post</p>") is None


def test_parse_settings_reads_the_text_the_date_the_place_and_the_employer():
    ad = v.parse_settings(_settings("2dc1cf30-de83-4ee2-aa48-29457e86e557"))
    assert ad["organization"] == "Region Västerbotten" and ad["location"] == "Umeå"
    assert ad["posted_at"] == datetime(2026, 9, 16)
    assert ad["description"].startswith("Om arbetsplatsen\n") and "Arbetsuppgifter\n" in ad["description"]
    assert v.parse_settings({}) is None and v.parse_settings({"Status": 0}) is None and v.parse_settings([]) is None


def test_a_list_page_entry_is_its_own_alive_check_and_name_page():
    page = "https://www.uppsala.se/jobb/lediga-jobb/"
    assert v.alive_url(page) == page and v.name_page(page, "https://recruit.visma.com/x") == page
