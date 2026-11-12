"""A Visma Recruit ad link is looked through for the employer's name and site, which `_classify` then follows
as it does any employer (issue #526): the site's own platform first, then the name's feeds."""

import json
import re

import pytest
import responses

from door.commands import companies as companies_cmd
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "visma_recruit"
_SETTINGS = "https://recruit.visma.com/Services/Public/Apply/GetApplySettings"
_AD = "https://recruit.visma.com/spa/public/apply?guidAssignment=2b368797-8e2c-4527-bc80-7cc9ac2d9c39"
_SITE = "https://www.alingsas.se/naringsliv-och-arbete/jobb/"
_TITLE = "Enhetschef inom funktionsstöd - Barnboende"
_COMPANY = {"company": "Alingsås", "links": [_AD], "postings": 1, "sources": {"jobindex"}, "titles": [_TITLE]}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr(companies_cmd, "_cname", lambda host: None)
    monkeypatch.setattr(companies_cmd, "_resolves", lambda host: False)


def _payload(site=True):
    data = json.loads((_FX / "get_apply_settings.json").read_text(encoding="utf-8"))
    if not site:
        data["Assignment"]["ReadMoreLink"] = {"Url": "", "Text": ""}
    return data


def _no_board(*patterns):
    for pattern in patterns:
        responses.add(responses.GET, re.compile(pattern), status=404)


def _classify(company=_COMPANY):
    return companies_cmd._classify(companies_cmd._session(), dict(company), set())


@responses.activate
def test_the_employers_own_site_named_in_the_ad_is_followed():
    responses.add(responses.GET, _SETTINGS, json=_payload())
    responses.add(responses.GET, _SITE, body='<script src="https://boards.greenhouse.io/embed/job_board/js?for=alingsas"></script>')

    kind, item = _classify()

    assert (kind, item["platform"], item["entry"]) == ("suggestions", "greenhouse", "alingsas")
    assert "Visma Recruit" in item["evidence"] and "Alingsås kommun" in item["evidence"]


@responses.activate
def test_without_a_site_the_employers_name_is_tried_on_the_feeds():
    responses.add(responses.GET, _SETTINGS, json=_payload(site=False))
    responses.add(responses.GET, re.compile(r"https://boards-api\.greenhouse\.io/v1/boards/alingsaaskommun/jobs.*"),
                  json={"jobs": [{"id": 1, "title": _TITLE, "location": {"name": "Alingsås"}}]})
    _no_board(r"https://.*")

    kind, item = _classify()

    assert (kind, item["platform"], item["entry"]) == ("suggestions", "greenhouse", "alingsaaskommun")
    assert "Visma Recruit" in item["evidence"]


@responses.activate
def test_a_feed_found_by_the_name_must_still_match_the_queued_jobs():
    responses.add(responses.GET, _SETTINGS, json=_payload(site=False))
    responses.add(responses.GET, re.compile(r"https://boards-api\.greenhouse\.io/v1/boards/alingsaaskommun/jobs.*"),
                  json={"jobs": [{"id": 1, "title": "Sales Manager", "location": {"name": "Austin"}}]})
    _no_board(r"https://.*")

    kind, item = _classify()

    assert (kind, item["platform"], item["refusal"]) == ("unfollowable", "visma_recruit", "cant_yet")


@responses.activate
def test_when_nothing_is_found_the_employer_stays_unfollowable_cant_yet():
    responses.add(responses.GET, _SETTINGS, json=_payload())
    responses.add(responses.GET, _SITE, body="<p>Lediga jobb finns på Visma Recruit.</p>")
    _no_board(r"https://.*")

    kind, item = _classify()

    assert (kind, item["platform"], item["refusal"]) == ("unfollowable", "visma_recruit", "cant_yet")
    assert "Visma Recruit" in item["evidence"]


@responses.activate
def test_when_the_json_cannot_be_read_the_employer_stays_unfollowable_cant_yet():
    responses.add(responses.GET, _SETTINGS, status=403)
    _no_board(r"https://.*")

    kind, item = _classify()

    assert (kind, item["platform"], item["refusal"]) == ("unfollowable", "visma_recruit", "cant_yet")


# --- an employer whose own website links its Visma Recruit job list is followed on it (issue #567) -------------------

_LIST_RE = re.compile(r"https://recruit\.visma\.com/External/OJCustomer3/AssignmentList\.aspx.*")
_NASSJO_AD = "https://recruit.visma.com/spa/public/apply?guidAssignment=ecb17166-7aaf-4103-acb9-8c6bc6cefc75"
_SKURUP_AD = "https://recruit.visma.com/spa/public/apply?guidAssignment=9ca86cfd-e913-4be2-8f08-66d7c7a7c671"
_NASSJO_ID = "f636d73d-8356-43c6-99bd-ba01addf1b55"
_SKURUP_ID = "e4de127c-0647-4402-83ee-c28fbb4803e8"


def _read(name):
    return (_FX / name).read_text(encoding="utf-8")


@responses.activate
def test_an_ad_link_is_followed_to_the_list_the_employers_website_links():
    company = {"company": "Nässjö", "links": [_NASSJO_AD], "postings": 1, "sources": {"jobindex"}, "titles": ["Bibliotekarie"]}
    responses.add(responses.GET, _SETTINGS, json=json.loads(_read("get_apply_settings_nassjo.json")))
    responses.add(responses.GET, "https://www.nassjo.se/", body=_read("nassjo_site.html"))
    responses.add(responses.GET, _LIST_RE, body=_read("nassjo_list.html"))

    kind, item = _classify(company)

    assert (kind, item["platform"], item["entry"], item["config_key"]) == (
        "suggestions", "visma_recruit", _NASSJO_ID, "visma_recruit_companies")
    assert "Visma Recruit" in item["evidence"] and "https://www.nassjo.se/" in item["evidence"]


@responses.activate
def test_a_municipality_whose_list_is_one_careers_page_deeper_is_followed_too():
    company = {"company": "Skurup", "links": [_SKURUP_AD], "postings": 1, "sources": {"jobindex"}, "titles": ["Skolsköterska"]}
    responses.add(responses.GET, _SETTINGS, json=json.loads(_read("get_apply_settings_skurup.json")))
    responses.add(responses.GET, "https://www.skurup.se/", body=_read("skurup_home.html"))
    responses.add(responses.GET, "https://www.skurup.se/jobb-och-foretagande/jobb-och-praktik/lediga-jobb-i-kommunen",
                  body=_read("skurup_site.html"))
    responses.add(responses.GET, _LIST_RE, body=_read("skurup_list.html"))

    kind, item = _classify(company)

    assert (kind, item["platform"], item["entry"]) == ("suggestions", "visma_recruit", _SKURUP_ID)
    assert "skurup.se" in item["evidence"]


@responses.activate
def test_the_employers_own_page_that_links_the_list_is_followed():
    company = {"company": "Nässjö kommun", "links": ["https://www.nassjo.se/"], "postings": 1, "sources": {"jobindex"}}
    responses.add(responses.GET, "https://www.nassjo.se/", body=_read("nassjo_site.html"))
    responses.add(responses.GET, _LIST_RE, body=_read("nassjo_list.html"))

    kind, item = _classify(company)

    assert (kind, item["platform"], item["entry"]) == ("suggestions", "visma_recruit", _NASSJO_ID)


@responses.activate
def test_a_website_that_links_no_list_leaves_the_employer_unfollowable_cant_yet():
    """Uppsala kommun, Region Gävleborg and the like keep their own list and send only the apply link to Visma."""
    company = {"company": "Nässjö", "links": [_NASSJO_AD], "postings": 1, "sources": {"jobindex"}, "titles": ["x"]}
    responses.add(responses.GET, _SETTINGS, json=json.loads(_read("get_apply_settings_nassjo.json")))
    responses.add(responses.GET, "https://www.nassjo.se/", body="<p>Vi är en kommun.</p>")
    _no_board(r"https://.*")

    kind, item = _classify(company)

    assert (kind, item["platform"], item["refusal"]) == ("unfollowable", "visma_recruit", "cant_yet")


@responses.activate
def test_a_list_that_no_longer_exists_is_not_followed():
    company = {"company": "Nässjö kommun", "links": ["https://www.nassjo.se/"], "postings": 1, "sources": {"jobindex"}}
    responses.add(responses.GET, "https://www.nassjo.se/", body=_read("nassjo_site.html"))
    responses.add(responses.GET, _LIST_RE, status=404, body="Sidan kunde inte hittas.")
    _no_board(r"https://.*")

    result = _classify(company)

    assert result is None or result[0] != "suggestions"


# --- an employer that lists its Visma ads on its own website: the list page is the entry (issue #567) ----------------

_ANY_SETTINGS = re.compile(r"https://recruit\.visma\.com/Services/Public/Apply/GetApplySettings.*")


def _settings_by_guid(*guids):
    for guid in guids:
        responses.add(responses.GET, _SETTINGS, match=[responses.matchers.query_param_matcher({"guidAssignment": guid})],
                      body=_read(f"settings_{guid}.json"), content_type="application/json")


@responses.activate
def test_a_region_that_lists_its_ads_with_their_visma_ids_is_followed_on_its_list_page():
    vb = ["2dc1cf30-de83-4ee2-aa48-29457e86e557", "54cb6759-74eb-415f-96e0-600ed6921971", "7c121586-df86-4e26-aa4c-a37efb90f6ad"]
    company = {"company": "Region Västerbotten", "links": [f"https://recruit.visma.com/spa/public/apply?guidAssignment={vb[0]}"],
               "postings": 1, "sources": {"jobindex"}, "titles": ["Sjuksköterska"]}
    _settings_by_guid(*vb)
    responses.add(responses.GET, "https://www.regionvasterbotten.se/", body=_read("vasterbotten_home.html"))
    responses.add(responses.GET, "https://www.regionvasterbotten.se/sok-jobb", body=_read("vasterbotten_list.html"))

    kind, item = _classify(company)

    assert (kind, item["platform"], item["entry"], item["config_key"]) == (
        "suggestions", "visma_recruit", "https://www.regionvasterbotten.se/sok-jobb", "visma_recruit_companies")
    assert "https://www.regionvasterbotten.se/sok-jobb" in item["evidence"]


@responses.activate
def test_a_region_whose_ad_pages_link_the_visma_apply_page_is_followed_on_its_list_page():
    ids = {1457976: "79d91229-63ef-4ec0-b958-42f1410a7b28", 1455047: "10085956-1d22-4f5f-8b8e-15de44fbedaa",
           1457635: "f76c7b12-a518-49d2-9303-951574c2d1e3"}
    company = {"company": "Region Gävleborg", "links": [f"https://recruit.visma.com/spa/public/apply?guidAssignment={ids[1457976]}"],
               "postings": 1, "sources": {"jobindex"}, "titles": ["x"]}
    _settings_by_guid(*ids.values())
    responses.add(responses.GET, "https://www.regiongavleborg.se/", body=_read("gavleborg_home.html"))
    list_url = "https://www.regiongavleborg.se/jobb-och-utbildning/lediga-jobb/"
    responses.add(responses.GET, list_url, body=_read("gavleborg_list.html"))
    for i, n in enumerate(ids, 1):
        responses.add(responses.GET, f"{list_url}{n}/", body=_read(f"gavleborg_ad_{i}.html"))

    kind, item = _classify(company)

    assert (kind, item["platform"], item["entry"]) == ("suggestions", "visma_recruit", list_url)


@responses.activate
def test_a_list_whose_ads_are_another_employers_is_not_followed():
    vb = "2dc1cf30-de83-4ee2-aa48-29457e86e557"
    company = {"company": "Region Gävleborg", "links": ["https://recruit.visma.com/spa/public/apply?guidAssignment=79d91229-63ef-4ec0-b958-42f1410a7b28"],
               "postings": 1, "sources": {"jobindex"}, "titles": ["x"]}
    _settings_by_guid("79d91229-63ef-4ec0-b958-42f1410a7b28", vb, "54cb6759-74eb-415f-96e0-600ed6921971", "7c121586-df86-4e26-aa4c-a37efb90f6ad")
    responses.add(responses.GET, "https://www.regiongavleborg.se/", body=_read("vasterbotten_home.html"))   # a namesake's site
    responses.add(responses.GET, "https://www.regionvasterbotten.se/sok-jobb", body=_read("vasterbotten_list.html"))
    _no_board(r"https://.*")

    kind, item = _classify(company)

    assert (kind, item["platform"], item["refusal"]) == ("unfollowable", "visma_recruit", "cant_yet")


@responses.activate
def test_the_ad_pages_are_found_among_the_lists_other_links_by_their_depth():
    """Region Kronoberg's list links its own sections before its ads, which lie one directory deeper."""
    ids = {1457976: "79d91229-63ef-4ec0-b958-42f1410a7b28", 1455047: "10085956-1d22-4f5f-8b8e-15de44fbedaa",
           1457635: "f76c7b12-a518-49d2-9303-951574c2d1e3"}
    company = {"company": "Region Gävleborg", "links": [f"https://recruit.visma.com/spa/public/apply?guidAssignment={ids[1457976]}"],
               "postings": 1, "sources": {"jobindex"}, "titles": ["x"]}
    _settings_by_guid(*ids.values())
    base = "https://www.regiongavleborg.se/jobb-och-utbildning/lediga-jobb/"
    sections = "".join(f'<a href="/jobb-och-utbildning/lediga-jobb/avsnitt-{n}/">Avsnitt {n}</a>' for n in range(1, 6))
    listing = sections + _read("gavleborg_list.html").replace("/lediga-jobb/14", "/lediga-jobb/lediga-jobb/14")
    responses.add(responses.GET, "https://www.regiongavleborg.se/", body=_read("gavleborg_home.html"))
    responses.add(responses.GET, base, body=listing)
    for n in range(1, 6):
        responses.add(responses.GET, f"{base}avsnitt-{n}/", body="<p>Om oss</p>")
    for i, n in enumerate(ids, 1):
        responses.add(responses.GET, f"{base}lediga-jobb/{n}/", body=_read(f"gavleborg_ad_{i}.html"))

    kind, item = _classify(company)

    assert (kind, item["platform"], item["entry"]) == ("suggestions", "visma_recruit", base)
    assert sum("avsnitt" in c.request.url for c in responses.calls) == 0   # the ads were tried first


@responses.activate
def test_the_websites_start_page_is_never_the_list_even_when_it_teases_a_few_ads():
    vb = ["2dc1cf30-de83-4ee2-aa48-29457e86e557", "54cb6759-74eb-415f-96e0-600ed6921971", "7c121586-df86-4e26-aa4c-a37efb90f6ad"]
    company = {"company": "Region Västerbotten", "links": [f"https://recruit.visma.com/spa/public/apply?guidAssignment={vb[0]}"],
               "postings": 1, "sources": {"jobindex"}, "titles": ["x"]}
    _settings_by_guid(*vb)
    teaser = f'<a href="/jobb?itemid={vb[0]}">Sjuksköterska</a><a href="/jobb?itemid={vb[1]}">Läkare</a>'
    responses.add(responses.GET, "https://www.regionvasterbotten.se/", body=_read("vasterbotten_home.html").replace("<nav>", "<nav>" + teaser))
    responses.add(responses.GET, "https://www.regionvasterbotten.se/sok-jobb", body=_read("vasterbotten_list.html"))

    kind, item = _classify(company)

    assert (kind, item["entry"]) == ("suggestions", "https://www.regionvasterbotten.se/sok-jobb")
