"""Oracle Cloud HCM (issue #438): the entry (host + site), link detection, and the pure mappers."""

import json
from datetime import datetime, timezone

import pytest
import responses

from door.scrapers.feeds import oracle_hcm
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "oracle_hcm"
_NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)


def _fx(name):
    return json.loads((_FX / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("url, entry", [
    ("https://efzu.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/8384", "efzu.fa.em2.oraclecloud.com/CX_1"),
    ("https://efzu.fa.em2.oraclecloud.eu/hcmUI/CandidateExperience/da/sites/CX_1001/requisitions?lastSelectedFacet=X",
     "efzu.fa.em2.oraclecloud.eu/CX_1001"),
    ("https://EJQI.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience/en/sites/CX_1001", "ejqi.fa.ocs.oraclecloud.eu/CX_1001"),
])
def test_a_candidate_experience_link_names_host_and_site(url, entry):
    det = oracle_hcm.detect_url(url)
    assert (det.platform, det.entry) == ("oracle_hcm", entry)
    assert det.config_key == "oracle_hcm_companies" and det.refusal is None


def test_a_link_without_a_site_names_the_host_but_no_entry_yet():
    det = oracle_hcm.detect_url("https://ejqi.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience/en/")
    assert det.platform == "oracle_hcm" and det.entry is None and det.refusal == "cant_yet"


def test_other_oracle_cloud_links_are_not_hcm():
    assert oracle_hcm.detect_url("https://efzu.fa.em2.oraclecloud.com/other/path") is None
    assert oracle_hcm.detect_url("https://acme.dk/hcmUI/CandidateExperience/en/sites/CX_1") is None


def test_the_terms_are_recorded_in_the_module():
    assert oracle_hcm.TERMS_URL == "https://www.oracle.com/legal/terms.html"
    assert "express written permission" in oracle_hcm.__doc__


def test_an_entry_is_a_host_and_a_site_or_a_link_to_one():
    assert oracle_hcm._entry("ejqi.fa.ocs.oraclecloud.eu/CX_1001") == ("ejqi.fa.ocs.oraclecloud.eu", "CX_1001")
    assert oracle_hcm._entry("https://ejqi.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience/en/sites/CX_1001/job/1") == (
        "ejqi.fa.ocs.oraclecloud.eu", "CX_1001")
    assert oracle_hcm._entry("ejqi.fa.ocs.oraclecloud.eu") is None
    assert oracle_hcm._entry("nonsense") is None


def test_the_search_url_asks_for_one_page_newest_first():
    url = oracle_hcm._search_url("h.oraclecloud.com", "CX_1", offset=50, limit=25)
    assert url.startswith("https://h.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?")
    assert "finder=findReqs;siteNumber=CX_1,limit=25,offset=50,sortBy=POSTING_DATES_DESC" in url


def test_the_job_link_is_the_candidate_experience_page():
    assert oracle_hcm._job_url("h.oraclecloud.com", "CX_1", "24218") == (
        "https://h.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/24218")


@pytest.mark.parametrize("item, expected", [
    ({"PrimaryLocation": "Vilnius, Lithuania", "PrimaryLocationCountry": "LT", "WorkplaceTypeCode": "ORA_HYBRID"},
     "Vilnius, Lithuania"),  # (a hybrid job is at its place: "Hybrid" would pass the local-jobs rule as remote)
    ({"PrimaryLocation": "Copenhagen", "PrimaryLocationCountry": "DK", "WorkplaceTypeCode": "ORA_REMOTE",
      "secondaryLocations": [{"Name": "Aarhus, Denmark", "CountryCode": "DK"}]}, "Remote, Copenhagen, DK; Aarhus, Denmark"),
    ({"PrimaryLocation": "Birkerod, Denmark", "PrimaryLocationCountry": "DK", "WorkplaceTypeCode": "ORA_ON_SITE"}, "Birkerod, Denmark"),
    ({"PrimaryLocation": None, "WorkplaceTypeCode": None}, ""),
])
def test_the_location_names_the_places_and_the_workplace_type(item, expected):
    assert oracle_hcm._location_text(item) == expected


def test_a_requisition_maps_to_a_posting_with_a_tenant_qualified_id():
    item = _fx("jobs_page1.json")["items"][0]["requisitionList"][0]
    posting = oracle_hcm._to_posting(item, "ejqi.fa.ocs.oraclecloud.eu", "CX_1001", "Danske Bank", _NOW)
    assert posting["platform_id"] == "ejqi.fa.ocs.oraclecloud.eu-24218"
    assert posting["id"].startswith("oracle_hcm.") and posting["source"] == "oracle_hcm"
    assert posting["title"] == "Product Owner - Platform" and posting["company"] == "Danske Bank"
    assert posting["posted_at"].startswith("2026-10-30")
    assert posting["url"] == "https://ejqi.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience/en/sites/CX_1001/job/24218"
    assert posting["description"].startswith("Join the platform team")  # the short text until the detail is read


def test_a_detail_gives_the_full_description_as_text():
    text = oracle_hcm._description(_fx("detail_24218.json")["items"][0])
    assert "lead four product teams" in text and "&amp;" not in text and "<" not in text


# --- resolving a link against the host's site list -------------------------------------------------------------

@pytest.fixture
def session():
    from door.scrapers.http_client import PoliteSession

    return PoliteSession(min_delay=0, max_delay=0, timeout=5, max_retries=0)


_SITES = "https://h.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCESites"
_LINK = "https://h.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/{}"


@responses.activate
def test_an_active_site_stays_as_named(session):
    responses.add(responses.GET, _SITES, json=_fx("sites_one_active.json"))
    det = oracle_hcm.detect_url(_LINK.format("CX_1001"))
    assert oracle_hcm.resolve(session, det, _LINK.format("CX_1001")) == det


@responses.activate
def test_an_inactive_site_becomes_the_one_active_site(session):
    responses.add(responses.GET, _SITES, json=_fx("sites_one_active.json"))
    link = _LINK.format("CX_4001")
    out = oracle_hcm.resolve(session, oracle_hcm.detect_url(link), link)
    assert out.entry == "h.fa.em2.oraclecloud.com/CX_1001" and "CX_4001" in out.evidence and "CX_1001" in out.evidence


@responses.activate
def test_a_link_with_no_site_takes_the_only_active_site(session):
    responses.add(responses.GET, _SITES, json=_fx("sites_one_active.json"))
    link = "https://h.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/"
    out = oracle_hcm.resolve(session, oracle_hcm.detect_url(link), link)
    assert out.entry == "h.fa.em2.oraclecloud.com/CX_1001"


@responses.activate
def test_an_inactive_site_on_a_shared_host_is_not_guessed(session):
    """Several employers share the host (the UN's): which one is meant is for the user to say."""
    responses.add(responses.GET, _SITES, json=_fx("sites_shared.json"))
    link = _LINK.format("CX_7")
    out = oracle_hcm.resolve(session, oracle_hcm.detect_url(link), link)
    assert out.entry is None and out.refusal == "cant_yet" and "CX_1" in out.evidence and "CX_2003" in out.evidence


@responses.activate
def test_a_site_list_that_cannot_be_read_leaves_the_detection_alone(session):
    responses.add(responses.GET, _SITES, status=500)
    det = oracle_hcm.detect_url(_LINK.format("CX_4001"))
    assert oracle_hcm.resolve(session, det, _LINK.format("CX_4001")) == det


def test_the_feed_check_is_the_one_job_search():
    assert oracle_hcm.feed_url("h.oraclecloud.com/CX_1") is None
    assert "limit=1" in oracle_hcm.alive_url("h.oraclecloud.com/CX_1")
    assert oracle_hcm.alive_url("nonsense") is None
