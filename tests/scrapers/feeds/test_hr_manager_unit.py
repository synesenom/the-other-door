"""Unit tests for the Talentech HR-Manager feed's pure helpers (issue #228)."""

import json

import pytest

from door.scrapers.feeds import hr_manager
from paths import TESTS_DIR

_FIX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "hr_manager"


def _item(name: str, i: int = 0) -> dict:
    return json.loads((_FIX / name).read_text(encoding="utf-8"))["Items"][i]


@pytest.mark.parametrize("raw, iso", [
    ("/Date(1790247013000+0200)/", "2026-09-24T12:50:13+02:00"),
    ("/Date(1790247013000-0130)/", "2026-09-24T09:20:13-01:30"),
    ("/Date(1790247013000)/", "2026-09-24T10:50:13+00:00"),
])
def test_parse_dotnet_date(raw, iso):
    assert hr_manager._parse_dotnet_date(raw).isoformat() == iso


@pytest.mark.parametrize("raw", [None, "", "2026-01-01", "/Date(-62135596800000)/", 17])
def test_parse_dotnet_date_rejects_what_is_not_a_date(raw):
    """The feed's 'no date' is year 1 (StartDate when ASAP)."""
    assert hr_manager._parse_dotnet_date(raw) is None


def test_location_is_the_departments_city():
    assert hr_manager._location_text(_item("kkdk_page1.json")) == "København S"


def test_location_falls_back_to_the_deepest_city_in_the_tree_then_the_position_location():
    item = {"Department": {"City": ""}, "DepartmentTree": {"Name": "Region", "City": "", "SubItems": [
        {"Name": "Rigshospitalet", "City": "København Ø", "SubItems": [{"Name": "Afdeling", "City": "", "SubItems": []}]}]}}
    assert hr_manager._location_text(item) == "København Ø"
    bare = {"Department": {}, "DepartmentTree": None, "PositionLocation": {"Name": "Herlev og Gentofte Hospital"}}
    assert hr_manager._location_text(bare) == "Herlev og Gentofte Hospital"


def test_company_is_the_customer_except_on_the_states_recruitment_service():
    """Statens Rekrutteringsløsning recruits for every agency: the agency is the employer."""
    assert hr_manager._company(_item("kkdk_page1.json"), "Københavns Kommune") == "Københavns Kommune"
    assert hr_manager._company(_item("srl_page1.json"), "Statens Rekrutteringsløsning") == "Energistyrelsen"


def test_regional_customer_is_named_by_the_institution_under_its_grouping_level():
    """Region Hovedstaden: root / "Direktørområde N" (no site) / hospital (has a City) / ward."""
    region = "Region Hovedstaden"
    names = [hr_manager._company(it, region) for it in json.loads((_FIX / "regionh_page1.json").read_text(encoding="utf-8"))["Items"]]
    assert names == ["Herlev og Gentofte Hospital", "Bispebjerg og Frederiksberg Hospital",
                     "Center for Ejendomme", "Region Hovedstadens Akutberedskab"]


def test_company_stays_the_customer_when_the_tree_has_no_site_below_a_grouping_level():
    """BEC's departments are numbered units without a City: the customer is the employer."""
    bec = json.loads((_FIX / "bec_page1.json").read_text(encoding="utf-8"))["Items"]
    assert {hr_manager._company(it, "Bankernes EDB Central") for it in bec} == {"Bankernes EDB Central"}


def _tree(*nodes):
    """A department tree from (name, city) pairs, root first."""
    tree = None
    for name, city in reversed(nodes):
        tree = {"Name": name, "City": city, **({"SubItems": [tree]} if tree else {})}
    return {"DepartmentTree": tree}


def test_a_site_directly_under_the_root_is_not_an_institution_level():
    assert hr_manager._company(_tree(("Region X", "A"), ("Unit", "B"), ("Ward", "")), "Region X") == "Region X"
    assert hr_manager._company(_tree(("Region X", "A"), ("Group", ""), ("Hospital ", "B")), "Region X") == "Hospital"
    assert hr_manager._company(_tree(("Kommune", ""), ("Forvaltning", "B"), ("Kontor", "B")), "Kommune") == "Kommune"
    assert hr_manager._company({"DepartmentTree": None}, "Region X") == "Region X"

# --- feed detection (issue #282) ---

def _d(det):
    return None if det is None else (det.platform, det.entry)


@pytest.mark.parametrize("url, expected", [
    ("https://api.hr-manager.net/JobPortal.svc/kkdk/PositionList/json/", ("hr_manager", "kkdk")),
    ("https://candidate.hr-manager.net/Agent/Subscription.aspx?customer=regionh", ("hr_manager", "regionh")),
    ("https://candidate.hr-manager.net/ApplicationInit.aspx?cid=342&ProjectId=1", ("hr_manager", None)),
])
def test_detect_url(url, expected):
    det = hr_manager.detect_url(url)
    assert _d(det) == expected
    if expected[1] is None:  # followable, but an application link names the customer by number only
        assert det.evidence
    assert hr_manager.detect_url("https://candidate.hr-manager.net/Vacancies/List.aspx") is None
    assert hr_manager.detect_url("https://example.com/") is None
    assert hr_manager.feed_url("kkdk") is None


_HR_FIXTURES = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "hr_manager"


@pytest.mark.parametrize("fixture, alias", [
    ("ad_page_with_list_link.html", "andel"),
    ("ad_page_with_subscription_link.html", "statensrekrutteringsloesning_tr"),
    ("ad_page_without_alias.html", None),
])
def test_the_alias_is_read_from_a_customer_link_on_the_ad_page(fixture, alias):
    assert hr_manager.hr_manager_alias_from_html((_HR_FIXTURES / fixture).read_text(encoding="utf-8")) == alias


def test_an_ad_page_url_loses_its_skip_advertisement_parameter():
    url = "https://candidate.hr-manager.net/ApplicationInit.aspx?cid=277&ProjectId=1&SkipAdvertisement=True&MediaId=5"
    assert hr_manager.hr_manager_ad_page_url(url) == \
        "https://candidate.hr-manager.net/ApplicationInit.aspx?cid=277&ProjectId=1&MediaId=5"
    assert hr_manager.hr_manager_ad_page_url("https://candidate.hr-manager.net/Vacancies/List.aspx?cid=1") is None
    assert hr_manager.hr_manager_ad_page_url("https://example.com/ApplicationInit.aspx?cid=1") is None
    assert hr_manager.hr_manager_ad_page_url("https://candidate.hr-manager.net/ApplicationInit.aspx?x=1") is None


def test_the_cid_of_an_hr_manager_link_is_read():
    assert hr_manager.hr_manager_cid("https://candidate.hr-manager.net/ApplicationInit.aspx?cid=342&ProjectId=1") == "342"
    assert hr_manager.hr_manager_cid("https://candidate.hr-manager.net/ApplicationForm/SinglePageApplicationForm.aspx?cid=3010&x=1") == "3010"
    assert hr_manager.hr_manager_cid("https://example.com/?cid=3") is None
    assert hr_manager.hr_manager_cid("https://candidate.hr-manager.net/Agent/Subscription.aspx?customer=bec") is None


def test_the_cid_of_a_feed_item_is_read_from_its_advertisement_url():
    item = {"AdvertisementUrl": "https://candidate.hr-manager.net/ApplicationInit.aspx?cid=1017&ProjectId=71567&MediaId=5"}
    assert hr_manager.hr_manager_item_cid(item) == "1017"
    assert hr_manager.hr_manager_item_cid({}) is None


def test_the_state_portal_is_a_shared_feed():
    assert hr_manager.SHARED["statensrekrutteringsloesning_tr"] == ("Statens Rekrutteringsløsning", "3010")
    assert hr_manager.shared_alias_for_cid("3010") == "statensrekrutteringsloesning_tr"
    assert hr_manager.shared_alias_for_cid("342") is None
    assert hr_manager.shared_name("Statensrekrutteringsloesning_TR") == "Statens Rekrutteringsløsning"
    assert hr_manager.shared_name("bec") is None


def test_a_protocol_relative_customer_link_names_the_alias_when_the_ad_links_name_only_a_number():
    """ITU's vacancy page links its ads by `cid=` and its job agent as `//delta.hr-manager.net/...?customer=`."""
    html = (_HR_FIXTURES / "itu_vacancies.html").read_text(encoding="utf-8")
    det = hr_manager.detect_html(html, "https://en.itu.dk/About-ITU/Vacancies")
    assert det is not None and (det.platform, det.entry) == ("hr_manager", "ituniversitetet")


def test_detect_html_finds_nothing_without_a_customer_link():
    html = '<a href="https://candidate.hr-manager.net/ApplicationInit.aspx?cid=119&ProjectId=1">x</a>'
    assert hr_manager.detect_html(html, "https://en.itu.dk/vacancies") is None
    assert hr_manager.detect_html("<p>no links</p>", "https://x.dk/") is None
