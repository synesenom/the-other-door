"""Visma Recruit links are recognised but not followed (issue #526): an ad's link names an assignment, never a board."""

import pytest

from door.core import ats_detect
from door.scrapers.feeds import visma_recruit

_GUID = "2b368797-8e2c-4527-bc80-7cc9ac2d9c39"


@pytest.mark.parametrize("url", [
    f"https://recruit.visma.com/spa/public/apply?guidAssignment={_GUID}",
    f"https://recruit.visma.com/spa/sv/public/apply?guidAssignment={_GUID}&description=True",
    f"https://recruit.visma.com/Public/Assignment.aspx?guidAssignment={_GUID}",
    f"https://recruit.visma.com/External/OJCustomer3/AssignmentView.aspx?guidAssignment={_GUID}",
    "https://recruit.visma.com/spa/sv/public/careers/0c1df7ad-877b-4fac-b9b1-65a5479e63c9",
])
def test_a_visma_recruit_link_is_named_but_not_followed(url):
    det = visma_recruit.detect_url(url)
    assert det.platform == "visma_recruit" and det.entry is None
    assert "Visma Recruit" in det.evidence and det.refusal == "cant_yet"


def test_other_hosts_are_not_visma_recruit():
    assert visma_recruit.detect_url("https://www.visma.se/karriar") is None
    assert visma_recruit.detect_url("https://careers.visma.com/jobs") is None
    assert visma_recruit.detect_url("https://acme.se/jobb?u=recruit.visma.com") is None


def test_a_page_that_embeds_a_visma_recruit_ad_or_frame_is_a_visma_recruit_site():
    html = f'<a href="https://recruit.visma.com/spa/public/apply?guidAssignment={_GUID}">Ansök</a>'
    det = visma_recruit.detect_html(html, "https://www.alingsas.se/jobb")
    assert det.platform == "visma_recruit" and det.entry is None and det.refusal == "cant_yet"
    assert visma_recruit.detect_html("<p>x</p>", "https://www.alingsas.se/") is None


def test_a_link_to_visma_recruit_does_not_decide_which_platform_a_page_is_on():
    assert visma_recruit.LINK_PLATFORMS == ()


def test_the_dispatcher_knows_the_module():
    assert "visma_recruit" in ats_detect.PRECEDENCE
    det = ats_detect.from_url(f"https://recruit.visma.com/spa/public/apply?guidAssignment={_GUID}")
    assert (det.platform, det.entry, det.refusal) == ("visma_recruit", None, "cant_yet")


# --- the look-through (the ad's own JSON names the employer) -------------------------------------------------

import json  # noqa: E402
import re  # noqa: E402

import responses  # noqa: E402

from door.scrapers.http_client import PoliteSession  # noqa: E402
from paths import TESTS_DIR  # noqa: E402

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "visma_recruit"
_SETTINGS = "https://recruit.visma.com/Services/Public/Apply/GetApplySettings"
_AD = f"https://recruit.visma.com/spa/public/apply?guidAssignment={_GUID}"


def _fx(name="get_apply_settings.json"):
    return json.loads((_FX / name).read_text(encoding="utf-8"))


@pytest.fixture
def session():
    return PoliteSession(min_delay=0, max_delay=0, timeout=5, max_retries=0)


def test_the_employer_is_the_accounts_name_and_its_site_the_ads_read_more_link():
    assert visma_recruit.employer_of(_fx()) == ("Alingsås kommun", "https://www.alingsas.se/naringsliv-och-arbete/jobb/")


def test_a_site_the_schema_names_wins_over_the_read_more_link():
    payload = _fx("get_apply_settings_same_as.json")
    assert visma_recruit.employer_of(payload) == ("Alingsås kommun", "https://www.alingsas.se")


def test_a_read_more_link_that_is_a_job_board_or_not_a_link_is_no_site():
    payload = _fx()
    payload["Assignment"]["ReadMoreLink"]["Url"] = "https://www.glassdoor.com/jobb"
    assert visma_recruit.employer_of(payload) == ("Alingsås kommun", None)
    payload["Assignment"]["ReadMoreLink"]["Url"] = "mailto:hr@example.com"
    assert visma_recruit.employer_of(payload)[1] is None


def test_a_payload_without_an_account_name_names_no_employer():
    payload = _fx()
    payload["ApplicationSettings"]["AccountName"] = " "
    payload["SchemaOrgJson"] = "not json"
    assert visma_recruit.employer_of(payload) == (None, "https://www.alingsas.se/naringsliv-och-arbete/jobb/")
    assert visma_recruit.employer_of({}) == (None, None)


def test_the_name_falls_back_to_the_schemas_hiring_organization():
    payload = _fx()
    payload["ApplicationSettings"]["AccountName"] = ""
    assert visma_recruit.employer_of(payload)[0] == "Alingsås kommun"


def test_the_assignment_guid_is_read_from_every_ad_link_shape_and_not_from_a_career_site():
    assert visma_recruit.assignment_guid(_AD) == _GUID
    assert visma_recruit.assignment_guid(f"https://recruit.visma.com/Public/Assignment.aspx?guidAssignment={_GUID.upper()}") == _GUID
    assert visma_recruit.assignment_guid("https://recruit.visma.com/spa/sv/public/careers/0c1df7ad-877b-4fac-b9b1-65a5479e63c9") is None


@responses.activate
def test_resolve_hands_the_employers_name_and_site_to_follow(session):
    responses.add(responses.GET, _SETTINGS, json=_fx())
    det = visma_recruit.resolve(session, visma_recruit.detect_url(_AD), _AD)
    assert (det.platform, det.entry, det.refusal) == ("visma_recruit", None, "cant_yet")
    assert det.employer == "Alingsås kommun" and det.site == "https://www.alingsas.se/naringsliv-och-arbete/jobb/"
    assert "Alingsås kommun" in det.evidence
    assert len(responses.calls) == 1 and responses.calls[0].request.params == {"guidAssignment": _GUID}


@responses.activate
def test_resolve_leaves_a_career_site_link_alone_without_a_request(session):
    link = "https://recruit.visma.com/spa/sv/public/careers/0c1df7ad-877b-4fac-b9b1-65a5479e63c9"
    det = visma_recruit.detect_url(link)
    assert visma_recruit.resolve(session, det, link) == det
    assert len(responses.calls) == 0


@pytest.mark.parametrize("answer", [{"status": 403}, {"status": 500}, {"body": "<html>wall</html>"}, {"body": "[]"}])
@responses.activate
def test_resolve_leaves_the_detection_as_it_was_when_the_json_is_not_readable(session, answer):
    responses.add(responses.GET, _SETTINGS, **answer)
    det = visma_recruit.detect_url(_AD)
    assert visma_recruit.resolve(session, det, _AD) == det


@responses.activate
def test_resolve_leaves_the_detection_as_it_was_when_the_host_cannot_be_reached(session):
    det = visma_recruit.detect_url(_AD)
    assert visma_recruit.resolve(session, det, _AD) == det   # responses refuses the unmocked request


# --- a customer's public job list (issue #567): followed, entry = the list's guidExtSoftware ----------------------------

from datetime import datetime  # noqa: E402

_NASSJO = "f636d73d-8356-43c6-99bd-ba01addf1b55"
_SKURUP = "e4de127c-0647-4402-83ee-c28fbb4803e8"
_LIST_URL = "https://recruit.visma.com/External/OJCustomer3/AssignmentList.aspx"


def _html(name):
    return (_FX / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("url", [
    f"{_LIST_URL}?guidExtSoftware={_NASSJO}",
    f"{_LIST_URL}?GuidExtSoftware={_NASSJO.upper()}&currentpage=2",
    f"https://recruit.visma.com/External/OJCustomer3/AssignmentView.aspx?GuidExtSoftware={_NASSJO}&guid=ECB17166-7AAF-4103-ACB9-8C6BC6CEFC75&locId=1",
])
def test_a_customers_job_list_link_names_the_entry_to_follow(url):
    det = visma_recruit.detect_url(url)
    assert (det.platform, det.entry, det.refusal) == ("visma_recruit", _NASSJO, None)
    assert det.config_key == "visma_recruit_companies"


def test_an_ad_link_still_names_no_entry_even_beside_a_list_guid_it_does_not_have():
    det = visma_recruit.detect_url(f"https://recruit.visma.com/External/OJCustomer3/AssignmentView.aspx?guidAssignment={_GUID}")
    assert det.entry is None and det.refusal == "cant_yet"
    assert visma_recruit.detect_url(f"{_LIST_URL}?guidExtSoftware=not-a-guid").entry is None


@pytest.mark.parametrize("page, url, guid", [
    ("nassjo_site.html", "https://nassjo.se/", _NASSJO),
    ("skurup_site.html", "https://www.skurup.se/jobb", _SKURUP),   # the link sits in a javascript:window.open(...)
])
def test_an_employers_page_that_links_its_visma_list_is_followed(page, url, guid):
    det = visma_recruit.detect_html(_html(page), url)
    assert (det.platform, det.entry, det.refusal) == ("visma_recruit", guid, None)
    assert url in det.evidence
    found = ats_detect.from_html(_html(page), url)
    assert (found.platform, found.entry) == ("visma_recruit", guid)


def test_a_scheme_less_list_link_is_found_too():
    html = f'<iframe src="//recruit.visma.com/External/OJCustomer3/AssignmentList.aspx?guidExtSoftware={_SKURUP}&amp;x=1"></iframe>'
    assert visma_recruit.detect_html(html, "https://x.se/").entry == _SKURUP


def test_the_list_guid_is_read_from_an_entry_or_a_link():
    assert visma_recruit.list_guid(_NASSJO.upper()) == _NASSJO
    assert visma_recruit.list_guid(f"{_LIST_URL}?guidExtSoftware={_SKURUP}") == _SKURUP
    assert visma_recruit.list_guid("https://recruit.visma.com/spa/public/apply") is None
    assert visma_recruit.list_guid("nässjö") is None


def test_the_feed_contract_for_a_list():
    assert visma_recruit.feed_url(_NASSJO) is None
    assert visma_recruit.alive_url(_NASSJO) == f"{_LIST_URL}?guidExtSoftware={_NASSJO}"
    assert visma_recruit.NAME_FROM_PAGE is True
    assert visma_recruit.name_page(_NASSJO, "https://recruit.visma.com/x") == f"{_LIST_URL}?guidExtSoftware={_NASSJO}"
    assert visma_recruit.PLATFORM_DOMAINS == ("recruit.visma.com",)


def test_parse_list_reads_the_employer_and_every_row():
    name, rows = visma_recruit.parse_list(_html("nassjo_list.html"))
    assert name == "Nässjö kommun" and len(rows) == 3
    assert rows[0] == {
        "guid": "ecb17166-7aaf-4103-acb9-8c6bc6cefc75", "loc_id": "1",
        "title": "Specialistundersköterskor till äldreomsorgen hemtjänst",
        "department": "Socialförvaltningen", "published": None, "deadline": "2026-11-01"}
    assert rows[1]["title"] == "Bibliotekssamordnare" and rows[2]["guid"] == "c51c1737-0e85-41e1-b991-7657a50ab8e2"


def test_parse_list_reads_a_published_column_when_the_customer_shows_one():
    name, rows = visma_recruit.parse_list(_html("skurup_list.html"))
    assert name == "Skurups kommun" and len(rows) == 3
    assert rows[0]["published"] == "2026-10-06" and rows[0]["deadline"] == "2026-11-01"
    assert rows[0]["department"] == "Skol- och utbildningsförvaltningen - Rydsgårdsskolan"


def test_parse_list_of_an_empty_list_is_no_rows_and_of_another_page_an_error():
    assert visma_recruit.parse_list(_html("nassjo_list_empty.html"))[1] == []
    with pytest.raises(ValueError):
        visma_recruit.parse_list("<html><body>Maintenance</body></html>")


def test_parse_detail_reads_the_text_the_date_and_the_place():
    ad = visma_recruit.parse_detail(_html("nassjo_ad_1.html"))
    assert ad["location"] == "Nässjö" and ad["organization"] == "Nässjö kommun"
    assert ad["posted_at"] == datetime(2026, 9, 28)
    text = ad["description"]
    assert text.startswith("Om arbetsplatsen\n") and "Arbetsuppgifter\n" in text and "Kvalifikationer\n" in text
    assert "specialistundersköterska" in text.lower() and "<" not in text
    assert "Dela den här annonsen" not in text and "Ansök här" not in text


def test_parse_detail_takes_the_place_from_the_schema_when_the_page_gives_none():
    ad = visma_recruit.parse_detail(_html("skurup_ad.html"))
    assert ad["location"] == "Skolgatan 1, Rydsgård" and ad["posted_at"] == datetime(2026, 10, 6)
    assert "Rydsgårdsskolan" in ad["description"]


def test_parse_detail_of_a_page_without_an_ad_is_none():
    assert visma_recruit.parse_detail("<html><body><h1>Annonsen finns inte</h1></body></html>") is None


# --- from an ad link to the employer's list (issue #567) ----------------------------------------------------------------

def _nassjo_ad():
    return json.loads((_FX / "get_apply_settings_nassjo.json").read_text(encoding="utf-8"))


@responses.activate
def test_resolve_finds_the_list_on_the_employers_own_site_when_the_ad_names_no_site(session):
    ad = f"https://recruit.visma.com/spa/public/apply?guidAssignment=ecb17166-7aaf-4103-acb9-8c6bc6cefc75"
    responses.add(responses.GET, _SETTINGS, json=_nassjo_ad())
    responses.add(responses.GET, "https://www.nassjo.se/", body=_html("nassjo_site.html"))
    responses.add(responses.GET, _LIST_URL, body=_html("nassjo_list.html"))

    det = visma_recruit.resolve(session, visma_recruit.detect_url(ad), ad)

    assert (det.platform, det.entry, det.refusal) == ("visma_recruit", _NASSJO, None)
    assert det.employer == "Nässjö kommun" and "https://www.nassjo.se/" in det.evidence
    assert responses.calls[2].request.params == {"guidExtSoftware": _NASSJO, "currentpage": "1"}


@responses.activate
def test_resolve_does_not_follow_a_list_of_another_employer(session):
    """A namesake's site: the list's own employer name must be the ad's."""
    ad = "https://recruit.visma.com/spa/public/apply?guidAssignment=ecb17166-7aaf-4103-acb9-8c6bc6cefc75"
    responses.add(responses.GET, _SETTINGS, json=_nassjo_ad())
    responses.add(responses.GET, "https://www.nassjo.se/", body=_html("skurup_site.html"))
    responses.add(responses.GET, _LIST_URL, body=_html("skurup_list.html"))

    det = visma_recruit.resolve(session, visma_recruit.detect_url(ad), ad)

    assert det.entry is None and det.refusal == "cant_yet" and det.employer == "Nässjö kommun"


@responses.activate
def test_resolve_keeps_the_name_when_no_guessed_site_shows_a_list(session):
    ad = "https://recruit.visma.com/spa/public/apply?guidAssignment=ecb17166-7aaf-4103-acb9-8c6bc6cefc75"
    responses.add(responses.GET, _SETTINGS, json=_nassjo_ad())
    responses.add(responses.GET, re.compile(r"https://(www\.)?nassjo(kommun)?\.se/"), body="<p>Lediga jobb</p>")

    det = visma_recruit.resolve(session, visma_recruit.detect_url(ad), ad)

    assert det.entry is None and det.employer == "Nässjö kommun"
