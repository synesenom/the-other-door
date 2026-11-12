"""Fixture tests for Emply's vacancy API (issue #437): DanChurchAid's open jobs, trimmed and rewritten."""

import json
import re

import pytest
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local
from door.scrapers.feeds import emply
from paths import TESTS_DIR

_API = "https://dca.career.emply.com/api/integration/vacancy/get-page"


def _fx() -> dict:
    return json.loads((TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "emply" / "dca.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_maps_every_vacancy():
    responses.add(responses.POST, _API, json=_fx())

    postings = emply.scrape({"emply_tenants": ["dca"]})

    assert len(postings) == 3
    first = postings[0]
    JobPosting.model_validate(first)
    assert first["title"] == "Intern - Digital Learning, Learning Lab (DanChurchAid)"
    assert first["company"] == "DanChurchAid"  # the vacancy's department, until a followed name is given
    assert first["platform_id"] == "dca.career.emply.com-06mqt4"
    assert first["id"] == "emply.dca-career-emply-com-06mqt4"
    assert first["location"] == "Meldahlsgade, 3, 1613, København, Denmark"
    assert first["url"] == "https://dca.career.emply.com/en/ad/intern-digital-learning-learning-lab-danchurchaid/06mqt4"
    assert first["posted_at"].startswith("2026-10-12T12:32:47")
    assert first["description"].startswith("Join the learning team")
    assert "<" not in first["description"]
    assert first["source"] == "emply"
    assert postings[1]["url"].startswith("https://dca.career.emply.com/da/ad/")
    body = json.loads(responses.calls[0].request.body)
    assert body["sectionId"] is None and body["offset"] == 0


@responses.activate
def test_the_followed_name_wins():
    responses.add(responses.POST, _API, json=_fx())

    postings = emply.scrape({"emply_tenants": ["dca"], "_names": {"emply_tenants": {"dca": "DanChurchAid"}}})

    assert {p["company"] for p in postings} == {"DanChurchAid"}


@responses.activate
def test_it_pages_by_offset_until_the_count_is_read(monkeypatch):
    monkeypatch.setattr(emply, "_PAGE", 2)
    data = _fx()
    vacancies = data["vacancies"]

    def answer(request):
        offset = json.loads(request.body)["offset"]
        return 200, {}, json.dumps({"vacancies": vacancies[offset:offset + 2], "count": 3})

    responses.add_callback(responses.POST, _API, callback=answer)

    assert len(emply.scrape({"emply_tenants": ["dca"]})) == 3
    assert [json.loads(c.request.body)["offset"] for c in responses.calls] == [0, 2]


@responses.activate
def test_a_vacancy_listed_twice_counts_once():
    data = _fx()
    data["vacancies"].append(data["vacancies"][0])
    responses.add(responses.POST, _API, json=data)

    assert len(emply.scrape({"emply_tenants": ["dca"]})) == 3


@responses.activate
def test_an_unknown_tenant_is_a_recorded_error():
    responses.add(responses.POST, "https://nope.career.emply.com/api/integration/vacancy/get-page",
                  status=302, headers={"Location": "https://emply.com/"})
    responses.add(responses.POST, _API, json=_fx())

    drain_errors()
    assert len(emply.scrape({"emply_tenants": ["nope", "dca"]})) == 3
    assert "nope" in drain_errors()["emply"][0]


@responses.activate
def test_an_answer_without_vacancies_is_a_recorded_error():
    responses.add(responses.POST, _API, json={"unexpected": 1})

    drain_errors()
    assert emply.scrape({"emply_tenants": ["dca"]}) == []
    assert drain_errors()["emply"]


@responses.activate
def test_scrape_drops_vacancies_in_another_country():
    data = _fx()
    data["vacancies"][0]["location"] = "Vienna, Austria"
    responses.add(responses.POST, _API, json=data)
    drain_non_local("emply")

    postings = emply.scrape({"emply_tenants": ["dca"], "location": "Copenhagen, Denmark"})

    assert len(postings) == 2
    assert drain_non_local("emply") == 1


def test_no_tenants_no_request():
    assert emply.scrape({}) == []
    assert emply.probe({}) is None


@responses.activate
def test_probe_reads_the_first_tenant():
    responses.add(responses.POST, _API, json=_fx())

    result = emply.probe({"emply_tenants": ["dca", "other"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 3


@responses.activate
def test_probe_drift_without_a_vacancy_list():
    responses.add(responses.POST, _API, json={"jobs": []})

    assert emply.probe({"emply_tenants": ["dca"]})["structure_ok"] is False


# --- Aarhus University's embedded vacancy list (#431) ---

from datetime import date  # noqa: E402

_AU_PAGE = "https://international.au.dk/about/profile/vacant-positions/"
_AU_JOB = "https://international.au.dk/about/profile/vacant-positions/job/{}"
_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "emply"


@pytest.fixture
def _au(monkeypatch):
    monkeypatch.setattr(emply, "_today", lambda: date(2026, 10, 31))
    responses.add(responses.GET, _AU_PAGE, body=(_FX / "au_vacancies.html").read_text(encoding="utf-8"))
    job = (_FX / "au_job.html").read_text(encoding="utf-8")
    responses.add(responses.GET, re.compile(r"https://international\.au\.dk/about/profile/vacant-positions/job/.*"), body=job)


@responses.activate
def test_scrape_reads_a_page_entry_and_the_ad_text_of_each_new_vacancy(_au):
    postings = emply.scrape({"emply_tenants": [_AU_PAGE]})

    assert [p["platform_id"].rsplit("-", 1)[1] for p in postings] == ["45307", "44944", "45619"]   # the expired one is dropped
    for p in postings:
        JobPosting.model_validate(p)
        assert p["company"] == "Aarhus University"
        assert "ultrafast spectroscopy" in p["description"] and "<" not in p["description"]
    assert len([c for c in responses.calls if "/job/" in c.request.url]) == 3


@responses.activate
def test_a_known_vacancy_costs_no_detail_request(_au):
    known = frozenset({"international.au.dk-45307", "international.au.dk-44944"})

    postings = emply.scrape({"emply_tenants": [_AU_PAGE]}, known)

    assert [p["platform_id"] for p in postings] == ["international.au.dk-45619"]
    assert len([c for c in responses.calls if "/job/" in c.request.url]) == 1


@responses.activate
def test_the_followed_name_labels_the_page_entry(_au):
    config = {"emply_tenants": [_AU_PAGE], "_names": {"emply_tenants": {"international.au.dk/about/profile/vacant-positions": "AU"}}}
    assert {p["company"] for p in emply.scrape(config)} == {"AU"}


@responses.activate
def test_a_page_without_the_embedded_list_is_an_error_of_the_entry(monkeypatch):
    drain_errors()
    responses.add(responses.GET, _AU_PAGE, body="<html><body>Nothing here</body></html>")
    assert emply.scrape({"emply_tenants": [_AU_PAGE]}) == []
    assert any("no embedded" in e for e in drain_errors()["emply"])
