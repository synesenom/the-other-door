"""Fixture tests for Visma Recruit employers with their own ad list (issue #567)."""

import json
import re

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local, drain_pushback
from door.scrapers.feeds import visma_recruit as v
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "visma_recruit"
_SETTINGS = "https://recruit.visma.com/Services/Public/Apply/GetApplySettings"
_KEY = "visma_recruit_companies"
_VB = "https://www.regionvasterbotten.se/sok-jobb"
_VB_IDS = ["2dc1cf30-de83-4ee2-aa48-29457e86e557", "7c121586-df86-4e26-aa4c-a37efb90f6ad", "54cb6759-74eb-415f-96e0-600ed6921971"]
_UP = "https://www.uppsala.se/jobb/lediga-jobb/"
_UP_IDS = {  # ad page id -> Visma id, in list order
    "GSN-2026-01761": "7dfdb3da-5394-4919-9171-1bd50ffc3f8c", "UBN-2026-05557": "d357eabb-9964-4c24-854a-e74da880c1ae",
    "UBN-2026-05522": "ebac40a8-1d10-42ae-9ad6-4a2758547d54", "UBN-2026-05442": "8e4247a8-d09b-418d-b4a4-a9fb3999de6e",
    "KTN-2026-00333": "e8b59804-f9d2-42b8-9920-830dee2469d9"}
_GB = "https://www.regiongavleborg.se/jobb-och-utbildning/lediga-jobb/"
_GB_ADS = {1457976: "79d91229-63ef-4ec0-b958-42f1410a7b28", 1455047: "10085956-1d22-4f5f-8b8e-15de44fbedaa",
           1457635: "f76c7b12-a518-49d2-9303-951574c2d1e3"}
_UV = "https://www.uppvidinge.se/naringsliv-och-arbete/arbetsmarknad/lediga-jobb-i-kommunen.html"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _ad_json(guid: str, **kw):
    kw = kw or {"body": _fx(f"settings_{guid}.json"), "content_type": "application/json"}
    responses.add(responses.GET, _SETTINGS, match=[responses.matchers.query_param_matcher({"guidAssignment": guid})], **kw)


def _serve_vasterbotten(second: dict | None = None):
    """The list and its three ads; *second* replaces the answer for the second ad."""
    responses.add(responses.GET, _VB, body=_fx("vasterbotten_list.html"))
    for i, guid in enumerate(_VB_IDS):
        _ad_json(guid, **(second if i == 1 and second else {}))


def _serve_uppsala():
    responses.add(responses.GET, _UP, match=[responses.matchers.query_param_matcher({})], body=_fx("uppsala_list_1.html"))
    responses.add(responses.GET, _UP, match=[responses.matchers.query_param_matcher({"page": "1"})], body=_fx("uppsala_list_1.html"))
    responses.add(responses.GET, _UP, match=[responses.matchers.query_param_matcher({"page": "2"})], body=_fx("uppsala_list_2.html"))
    for n in ("3", "4"):
        responses.add(responses.GET, _UP, match=[responses.matchers.query_param_matcher({"page": n})], body=_fx("uppsala_list_empty.html"))
    ids = list(_UP_IDS)
    for i, ad in enumerate(ids):
        page, pos = (1, i + 1) if i < 3 else (2, i - 2)
        responses.add(responses.GET, _UP + "Details/", match=[responses.matchers.query_param_matcher({"id": ad})],
                      body=_fx(f"uppsala_ad_{page}_{pos}.html"))
        _ad_json(_UP_IDS[ad])


@responses.activate
def test_an_ad_list_that_carries_the_visma_ids_is_read_without_opening_the_employers_ad_pages():
    _serve_vasterbotten()
    drain_errors()

    postings = v.scrape({_KEY: [_VB]})

    assert len(postings) == 3
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "visma_recruit" and p["company"] == "Region Västerbotten"
        assert p["title"] and p["description"] and "<" not in p["description"]
        assert p["url"] == f"https://recruit.visma.com/spa/public/apply?guidAssignment={p['platform_id']}"
        assert p["id"] == f"visma_recruit.{p['platform_id']}"
    first = postings[0]
    assert first["platform_id"] == _VB_IDS[0] and first["location"] == "Umeå" and first["posted_at"].startswith("2026-09-16")
    assert [c.request.url.split("?")[0] for c in responses.calls] == [_VB] + [_SETTINGS] * 3
    assert drain_errors() == {}


@responses.activate
def test_known_ads_cost_no_request_and_are_not_returned():
    _serve_vasterbotten()

    postings = v.scrape({_KEY: [_VB]}, frozenset(_VB_IDS[:2]))

    assert [p["platform_id"] for p in postings] == [_VB_IDS[2]]
    assert len(responses.calls) == 2


@responses.activate
def test_the_followed_name_wins_and_the_page_entry_is_read_once():
    _serve_vasterbotten()

    postings = v.scrape({_KEY: [_VB, _VB + "#top"], "_names": {_KEY: {"www.regionvasterbotten.se/sok-jobb": "Region V"}}})

    assert len(postings) == 3 and {p["company"] for p in postings} == {"Region V"}


@responses.activate
def test_offentliga_jobb_links_are_read_through_the_same_json():
    responses.add(responses.GET, _UV, body=_fx("uppvidinge_list.html"))
    for guid in ("984ec35e-aa56-416d-9415-805a95e47244", "27f683a8-4c5f-4420-b155-a61379984ba9", "e94165db-d3a7-44c7-adfe-5604da06c244"):
        _ad_json(guid)

    postings = v.scrape({_KEY: [_UV]})

    assert len(postings) == 3 and {p["company"] for p in postings} == {"Uppvidinge kommun"}
    assert all("offentligajobb" not in c.request.url for c in responses.calls)


@responses.activate
def test_an_own_ad_list_is_paged_and_each_ad_page_gives_its_visma_id():
    _serve_uppsala()
    drain_errors()

    postings = v.scrape({_KEY: [_UP]})

    assert [p["platform_id"] for p in postings] == list(_UP_IDS.values())
    assert {p["company"] for p in postings} == {"Uppsala kommun"}
    pages = [c.request.url for c in responses.calls if c.request.url.startswith(_UP + "?") or c.request.url == _UP]
    assert len(pages) == 5   # the list itself and its paging, ?page=1 .. 4
    assert drain_errors() == {}


@responses.activate
def test_an_ad_page_with_no_visma_link_is_skipped_quietly():
    responses.add(responses.GET, _GB, body=_fx("gavleborg_list.html"))
    for i, (n, guid) in enumerate(_GB_ADS.items(), 1):
        responses.add(responses.GET, f"{_GB}{n}/", body=_fx(f"gavleborg_ad_{i}.html") if i < 3 else "<p>Ansök via e-post</p>")
        _ad_json(guid)
    drain_errors()

    postings = v.scrape({_KEY: [_GB]})

    assert [p["platform_id"] for p in postings] == list(_GB_ADS.values())[:2]
    assert drain_errors() == {}


@responses.activate
def test_an_ad_that_cannot_be_read_is_a_recorded_error_and_the_rest_stay():
    _serve_vasterbotten({"status": 404})
    drain_errors()

    postings = v.scrape({_KEY: [_VB]})

    assert [p["platform_id"] for p in postings] == [_VB_IDS[0], _VB_IDS[2]]
    assert len(drain_errors()["visma_recruit"]) == 1


@responses.activate
def test_a_closed_ad_is_skipped_without_an_error():
    _serve_vasterbotten({"json": {"Status": 0}})
    drain_errors()

    assert len(v.scrape({_KEY: [_VB]})) == 2
    assert drain_errors() == {}


@pytest.mark.parametrize("status", [429, 403])
@responses.activate
def test_pushback_from_visma_is_recorded_and_ends_the_list(status):
    _serve_vasterbotten({"status": status})
    drain_errors()
    drain_pushback("visma_recruit")

    assert [p["platform_id"] for p in v.scrape({_KEY: [_VB]})] == [_VB_IDS[0]]   # the refusal ends the list there

    assert drain_pushback("visma_recruit") is True
    assert drain_errors()["visma_recruit"]


@responses.activate
def test_a_list_page_that_fails_is_a_recorded_error_and_the_next_entry_goes_on():
    responses.add(responses.GET, _UV, status=500)
    _serve_vasterbotten()
    drain_errors()

    postings = v.scrape({_KEY: [_UV, _VB]})

    assert len(postings) == 3
    assert _UV in drain_errors()["visma_recruit"][0]


@responses.activate
def test_scrape_drops_ads_in_another_country():
    _serve_vasterbotten({"body": _fx(f"settings_{_VB_IDS[1]}.json").replace("Umeå", "Vienna, Austria"), "content_type": "application/json"})
    drain_non_local("visma_recruit")

    postings = v.scrape({_KEY: [_VB], "location": "Stockholm, Sweden"})

    assert len(postings) == 2 and drain_non_local("visma_recruit") == 1


@responses.activate
def test_probe_reads_the_list_page_with_one_request():
    responses.add(responses.GET, _VB, body=_fx("vasterbotten_list.html"))
    drain_errors()

    result = v.probe({_KEY: [_VB]})

    assert result["structure_ok"] is True and len(result["postings"]) == 3
    assert len(responses.calls) == 1 and drain_errors() == {}


@responses.activate
def test_probe_of_a_list_with_no_ads_or_links_is_drift():
    responses.add(responses.GET, _VB, body="<html><body><p>Inga jobb</p></body></html>")

    result = v.probe({_KEY: [_VB]})

    assert result["structure_ok"] is False and result["reason"]


@responses.activate
def test_probe_unreachable_and_wall():
    responses.add(responses.GET, _VB, body=requests.ConnectionError("down"))
    assert v.probe({_KEY: [_VB]}).get("unreachable") is True
    responses.replace(responses.GET, _VB, status=403)
    assert v.probe({_KEY: [_VB]}).get("wall") is True


@responses.activate
def test_a_slow_site_s_ad_pages_are_opened_only_within_the_time_budget(monkeypatch):
    """Region Gävleborg's robots.txt asks for 30 s between requests: its 75 ad pages would take 37 minutes."""
    _serve_uppsala()
    monkeypatch.setattr(v, "_AD_PAGE_BUDGET_S", 0)
    drain_errors()

    postings = v.scrape({_KEY: [_UP]})

    assert [p["platform_id"] for p in postings] == [list(_UP_IDS.values())[0]]   # the first ad page is always opened
    assert sum("/Details/" in c.request.url for c in responses.calls) == 1
    assert drain_errors() == {}
