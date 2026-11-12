"""Fixture tests for Visma Recruit's customer job lists (issue #567): Nässjö kommun's and Skurups kommun's
lists and ads, trimmed and their text rewritten."""

import pytest
import requests
import responses
from responses import matchers

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local, drain_pushback
from door.scrapers.feeds import visma_recruit
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "visma_recruit"
_NASSJO = "f636d73d-8356-43c6-99bd-ba01addf1b55"
_SKURUP = "e4de127c-0647-4402-83ee-c28fbb4803e8"
_LIST = "https://recruit.visma.com/External/OJCustomer3/AssignmentList.aspx"
_VIEW = "https://recruit.visma.com/External/OJCustomer3/AssignmentView.aspx"
_AD1, _AD2, _NO_AD = ("ECB17166-7AAF-4103-ACB9-8C6BC6CEFC75", "C51C1737-0E85-41E1-B991-7657A50AB8E2",
                      "3A0E9253-8700-4C70-83D5-19B609DADCB2")
_KEY = "visma_recruit_companies"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _list(guid: str, page: int, body: str | None = None, **kw):
    responses.add(responses.GET, _LIST, body=body, match=[matchers.query_param_matcher(
        {"guidExtSoftware": guid, "currentpage": str(page)})], **kw)


def _view(guid: str, ad: str, body: str | None = None, **kw):
    responses.add(responses.GET, _VIEW, body=body, match=[matchers.query_param_matcher(
        {"GuidExtSoftware": guid, "guid": ad, "locId": "1"})], **kw)


def _serve_nassjo(first_ad: str | None = None):
    _list(_NASSJO, 1, _fx("nassjo_list.html"))
    _list(_NASSJO, 2, _fx("nassjo_list_empty.html"))
    _view(_NASSJO, _AD1, first_ad or _fx("nassjo_ad_1.html"))
    _view(_NASSJO, _NO_AD, status=500)
    _view(_NASSJO, _AD2, _fx("nassjo_ad_2.html"))


@responses.activate
def test_scrape_maps_every_readable_ad_with_its_text_date_and_place():
    _serve_nassjo()
    drain_errors()

    postings = visma_recruit.scrape({_KEY: [_NASSJO]})

    assert [p["title"] for p in postings] == ["Specialistundersköterskor till äldreomsorgen hemtjänst",
                                              "Bibliotekarie sökes till Nässjö kommun"]
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "visma_recruit" and p["company"] == "Nässjö kommun" and p["location"] == "Nässjö"
        assert p["description"] and "<" not in p["description"]
    first = postings[0]
    assert first["id"] == "visma_recruit.ecb17166-7aaf-4103-acb9-8c6bc6cefc75"
    assert first["platform_id"] == "ecb17166-7aaf-4103-acb9-8c6bc6cefc75"
    assert first["url"] == "https://recruit.visma.com/spa/public/apply?guidAssignment=ecb17166-7aaf-4103-acb9-8c6bc6cefc75"
    assert first["apply_url"] == first["url"] and first["apply_type"] == "external"
    assert first["posted_at"].startswith("2026-09-28")
    assert first["description"].startswith("Om arbetsplatsen\n")


@responses.activate
def test_the_list_is_paged_until_a_page_with_no_ads():
    _serve_nassjo()

    visma_recruit.scrape({_KEY: [_NASSJO]})

    urls = [c.request.url for c in responses.calls]
    assert [u.split("currentpage=")[1] for u in urls if "AssignmentList" in u] == ["1", "2"]
    assert {u.split("guid=")[1].split("&")[0] for u in urls if "AssignmentView" in u} == {_AD1, _AD2, _NO_AD}


@responses.activate
def test_an_ad_that_cannot_be_read_is_a_recorded_error_and_the_rest_stay():
    _serve_nassjo()
    drain_errors()

    visma_recruit.scrape({_KEY: [_NASSJO]})

    errors = drain_errors()["visma_recruit"]
    assert len(errors) == 1 and "3a0e9253" in errors[0].lower()


@responses.activate
def test_known_ads_cost_no_detail_request_and_are_not_returned():
    _serve_nassjo()

    postings = visma_recruit.scrape({_KEY: [_NASSJO]}, frozenset({"ecb17166-7aaf-4103-acb9-8c6bc6cefc75", "3a0e9253-8700-4c70-83d5-19b609dadcb2"}))

    assert [p["platform_id"] for p in postings] == ["c51c1737-0e85-41e1-b991-7657a50ab8e2"]
    assert sum("AssignmentView" in c.request.url for c in responses.calls) == 1


@responses.activate
def test_the_followed_name_wins_and_a_link_is_an_entry_too():
    _serve_nassjo()
    link = f"{_LIST}?guidExtSoftware={_NASSJO.upper()}"

    postings = visma_recruit.scrape({_KEY: [_NASSJO, link], "_names": {_KEY: {_NASSJO: "Nässjö"}}})

    assert {p["company"] for p in postings} == {"Nässjö"} and len(postings) == 2   # one list, read once


@responses.activate
def test_a_customer_with_a_published_column_gives_the_date_when_the_ad_page_has_none():
    _list(_SKURUP, 1, _fx("skurup_list.html"))
    _list(_SKURUP, 2, _fx("nassjo_list_empty.html"))
    _view(_SKURUP, "9CA86CFD-E913-4BE2-8F08-66D7C7A7C671", _fx("skurup_ad.html").replace(
        '"datePosted":"2026-10-06T00:00:00",', ""))
    for ad in ("8F56FCDB-6E5E-445E-AE7A-C2C98EE6EB77", "6D08FDD5-3D27-4312-99E7-0821B145D075"):
        _view(_SKURUP, ad, status=404)

    postings = visma_recruit.scrape({_KEY: [_SKURUP]})

    assert len(postings) == 1
    assert postings[0]["company"] == "Skurups kommun" and postings[0]["location"] == "Skolgatan 1, Rydsgård"
    assert postings[0]["posted_at"].startswith("2026-10-06")


@responses.activate
def test_a_failed_list_is_a_recorded_error_not_a_raise_and_the_next_list_goes_on():
    _list(_SKURUP, 1, status=500)
    _serve_nassjo()
    drain_errors()

    postings = visma_recruit.scrape({_KEY: [_SKURUP, _NASSJO]})

    assert len(postings) == 2
    assert _SKURUP in drain_errors()["visma_recruit"][0]


@pytest.mark.parametrize("status", [429, 403])
@responses.activate
def test_pushback_is_recorded_and_ends_the_list(status):
    _list(_NASSJO, 1, status=status)
    drain_errors()
    drain_pushback("visma_recruit")

    assert visma_recruit.scrape({_KEY: [_NASSJO]}) == []

    assert drain_pushback("visma_recruit") is True
    assert drain_errors()["visma_recruit"]


@responses.activate
def test_an_unknown_list_is_a_recorded_error():
    _list(_NASSJO, 1, "Sidan kunde inte hittas.", status=404)
    drain_errors()

    assert visma_recruit.scrape({_KEY: [_NASSJO]}) == []
    assert drain_errors()["visma_recruit"]


@responses.activate
def test_a_page_that_is_not_a_list_is_a_recorded_error():
    _list(_NASSJO, 1, "<html><body>Maintenance</body></html>")
    drain_errors()

    assert visma_recruit.scrape({_KEY: [_NASSJO]}) == []
    assert drain_errors()["visma_recruit"]


@responses.activate
def test_scrape_drops_ads_in_another_country():
    _serve_nassjo(_fx("nassjo_ad_1.html").replace(">Nässjö<", ">Vienna, Austria<").replace(
        '"address":"Nässjö"', '"address":"Vienna, Austria"'))
    drain_non_local("visma_recruit")

    postings = visma_recruit.scrape({_KEY: [_NASSJO], "location": "Stockholm, Sweden"})

    assert [p["title"] for p in postings] == ["Bibliotekarie sökes till Nässjö kommun"]
    assert drain_non_local("visma_recruit") == 1


def test_no_entries_no_request():
    assert visma_recruit.scrape({}) == []
    assert visma_recruit.probe({}) is None


@responses.activate
def test_probe_reads_page_one_of_the_first_list_with_one_request():
    _list(_NASSJO, 1, _fx("nassjo_list.html"))
    drain_errors()

    result = visma_recruit.probe({_KEY: [_NASSJO, _SKURUP]})

    assert result["structure_ok"] is True and len(result["postings"]) == 3
    assert result["postings"][0]["company"] == "Nässjö kommun"
    assert len(responses.calls) == 1
    assert drain_errors() == {}


@responses.activate
def test_probe_drift_without_the_list():
    _list(_NASSJO, 1, _fx("nassjo_list.html").replace('<table id="list">', "<table>"))

    result = visma_recruit.probe({_KEY: [_NASSJO]})

    assert result["structure_ok"] is False and result["reason"]


@responses.activate
def test_probe_unreachable_and_wall():
    _list(_NASSJO, 1, body=requests.ConnectionError("down"))
    down = visma_recruit.probe({_KEY: [_NASSJO]})
    assert down["structure_ok"] is False and down.get("unreachable") is True
    responses.replace(responses.GET, _LIST, status=403, match=[matchers.query_param_matcher(
        {"guidExtSoftware": _NASSJO, "currentpage": "1"})])
    walled = visma_recruit.probe({_KEY: [_NASSJO]})
    assert walled["structure_ok"] is False and walled.get("wall") is True
