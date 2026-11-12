"""Fixture tests for the Oracle Cloud HCM candidate-experience feed (#438): a bank's career site, trimmed and
with its free text rewritten, served page by page."""

import json
import re
from urllib.parse import parse_qs, unquote, urlparse

import pytest
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local
from door.scrapers.feeds import oracle_hcm
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "oracle_hcm"
_HOST = "ejqi.fa.ocs.oraclecloud.eu"
_ENTRY = f"{_HOST}/CX_1001"
_BASE = f"https://{_HOST}/hcmRestApi/resources/latest"


def _fx(name):
    return (_FX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _small_pages(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr(oracle_hcm, "_PAGE", 2)


def _finder(request) -> dict:
    """The ``finder`` parameter of a request as a dict (``findReqs;siteNumber=CX_1001,limit=2,offset=0``)."""
    raw = unquote(urlparse(request.url).query)
    finder = re.search(r"finder=([^&]*)", raw).group(1)
    return dict(p.split("=", 1) for p in finder.split(";", 1)[1].split(","))


def _serve(details=("24218", "24001")):
    def search(request):
        offset = int(_finder(request)["offset"])
        return (200, {}, _fx("jobs_page1.json" if offset == 0 else "jobs_page2.json"))

    responses.add_callback(responses.GET, re.compile(rf"{re.escape(_BASE)}/recruitingCEJobRequisitions\?.*"), callback=search)
    for job in details:
        responses.add(responses.GET, re.compile(rf"{re.escape(_BASE)}/recruitingCEJobRequisitionDetails\?.*Id=%22{job}%22.*|"
                                                rf"{re.escape(_BASE)}/recruitingCEJobRequisitionDetails\?.*Id=\"{job}\".*"),
                      body=_fx(f"detail_{job}.json"))


def _detail_ids():
    return [re.search(r'Id="?(\d+)', unquote(c.request.url)).group(1)
            for c in responses.calls if "RequisitionDetails" in c.request.url]


@responses.activate
def test_scrape_pages_through_the_site_and_maps_every_posting():
    _serve()

    postings = oracle_hcm.scrape({"oracle_hcm_companies": [_ENTRY], "_names": {"oracle_hcm_companies": {_ENTRY.lower(): "Danske Bank"}}})

    assert [p["title"] for p in postings] == ["Product Owner - Platform", "Data Engineer", "Remote Analyst"]
    for p in postings:
        JobPosting.model_validate(p)
        assert p["company"] == "Danske Bank" and p["source"] == "oracle_hcm"
    assert postings[0]["platform_id"] == f"{_HOST}-24218"
    assert "lead four product teams" in postings[0]["description"] and "<" not in postings[0]["description"]
    assert postings[0]["posted_at"].startswith("2026-10-30")
    assert postings[2]["location"].startswith("Remote, Copenhagen")


@responses.activate
def test_the_detail_is_read_only_for_postings_not_seen_before():
    _serve(details=("24218", "24001"))
    known = frozenset({f"{_HOST}-24100"})

    postings = oracle_hcm.scrape({"oracle_hcm_companies": [_ENTRY]}, known)

    assert [p["platform_id"] for p in postings] == [f"{_HOST}-24218", f"{_HOST}-24001"]
    assert sorted(_detail_ids()) == ["24001", "24218"]


@responses.activate
def test_a_posting_whose_detail_fails_keeps_the_list_text():
    _serve(details=("24218",))
    responses.add(responses.GET, re.compile(rf"{re.escape(_BASE)}/recruitingCEJobRequisitionDetails.*"), status=500)

    postings = oracle_hcm.scrape({"oracle_hcm_companies": [_ENTRY]})

    by_title = {p["title"]: p for p in postings}
    assert by_title["Remote Analyst"]["description"] == "Analyse payment data."
    assert "lead four product teams" in by_title["Product Owner - Platform"]["description"]


@responses.activate
def test_postings_in_another_country_are_dropped_before_their_detail_is_read():
    _serve()
    drain_non_local("oracle_hcm")

    postings = oracle_hcm.scrape({"oracle_hcm_companies": [_ENTRY], "location": "Copenhagen, Denmark"})

    assert [p["title"] for p in postings] == ["Data Engineer", "Remote Analyst"]
    assert drain_non_local("oracle_hcm") == 1
    assert "24218" not in _detail_ids()  # the Budapest posting is never read


@responses.activate
def test_an_unreachable_site_is_a_recorded_error_and_the_rest_go_on():
    responses.add(responses.GET, re.compile(r"https://nope\.fa\.em2\.oraclecloud\.com/.*"), status=404)
    _serve()

    drain_errors()
    postings = oracle_hcm.scrape({"oracle_hcm_companies": ["nope.fa.em2.oraclecloud.com/CX_1", _ENTRY]})

    assert len(postings) == 3
    assert "nope.fa.em2.oraclecloud.com" in drain_errors()["oracle_hcm"][0]


@responses.activate
def test_a_site_with_no_jobs_is_an_empty_list():
    responses.add(responses.GET, re.compile(rf"{re.escape(_BASE)}/recruitingCEJobRequisitions.*"), body=_fx("jobs_empty.json"))
    assert oracle_hcm.scrape({"oracle_hcm_companies": [_ENTRY]}) == []


@responses.activate
def test_a_malformed_entry_is_a_recorded_error():
    drain_errors()
    assert oracle_hcm.scrape({"oracle_hcm_companies": ["nonsense"]}) == []
    assert "nonsense" in drain_errors()["oracle_hcm"][0]


def test_no_entries_no_request():
    assert oracle_hcm.scrape({}) == []
    assert oracle_hcm.probe({}) is None


@responses.activate
def test_probe_reads_page_one_of_the_first_site():
    responses.add_callback(responses.GET, re.compile(rf"{re.escape(_BASE)}/recruitingCEJobRequisitions\?.*"),
                           callback=lambda r: (200, {}, _fx("jobs_page1.json")))

    result = oracle_hcm.probe({"oracle_hcm_companies": [_ENTRY]})

    assert result["structure_ok"] and len(result["postings"]) == 2 and result["ext"] == "json"
    assert len(responses.calls) == 1  # (no detail request)


@responses.activate
def test_probe_flags_an_answer_without_the_requisition_list():
    responses.add(responses.GET, re.compile(rf"{re.escape(_BASE)}/recruitingCEJobRequisitions.*"), json={"items": [{"x": 1}]})
    assert oracle_hcm.probe({"oracle_hcm_companies": [_ENTRY]})["structure_ok"] is False
