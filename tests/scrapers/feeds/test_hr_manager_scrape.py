"""Fixture tests for the Talentech HR-Manager feed (issue #228).

Real `PositionList/json/` pages for Københavns Kommune (`kkdk`) and the state's
recruitment service, reduced to the fields The other door reads, the ad bodies rewritten.
"""

import json
import re

import pytest
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.feeds import hr_manager
from paths import TESTS_DIR

_FIX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "hr_manager"
_KKDK = "https://api.hr-manager.net/JobPortal.svc/kkdk/PositionList/json/"


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _small_pages(monkeypatch):
    monkeypatch.setattr(hr_manager, "_PAGE_SIZE", 2)
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _pages():
    from responses import matchers

    responses.add(responses.GET, _KKDK, body=_fx("kkdk_page1.json"),
                  match=[matchers.query_param_matcher({"take": "2", "skip": "0", "incads": "true"})])
    responses.add(responses.GET, _KKDK, body=_fx("kkdk_page2.json"),
                  match=[matchers.query_param_matcher({"take": "2", "skip": "2", "incads": "true"})])


@responses.activate
def test_scrape_pages_until_a_short_page_and_maps_every_field():
    _pages()

    postings = hr_manager.scrape({"hr_manager_aliases": ["kkdk"]})

    assert [p["platform_id"] for p in postings] == ["kkdk-216470", "kkdk-216557", "kkdk-216495"]
    first = postings[0]
    JobPosting.model_validate(first)
    assert first["title"].startswith("HR-generalist til organisations")  # zero-width characters gone
    assert first["company"] == "Københavns Kommune"
    assert first["location"] == "København S"
    assert first["source"] == "hr_manager"
    assert first["url"].startswith("https://candidate.hr-manager.net/ApplicationInit.aspx?cid=1518&ProjectId=216470")
    assert first["apply_url"] == first["url"] and first["apply_type"] == "external"
    assert first["posted_at"].startswith("2026-09-24")
    assert first["description"].startswith("Brænder du for HR")
    assert "<" not in first["description"]


@responses.activate
def test_an_unknown_alias_is_a_recorded_error_and_the_rest_continue():
    responses.add(responses.GET, "https://api.hr-manager.net/JobPortal.svc/nope/PositionList/json/", status=400,
                  json={"TransactionStatus": {"StatusCode": 1, "Description": "Value cannot be null."}, "Items": []})
    _pages()

    drain_errors()
    postings = hr_manager.scrape({"hr_manager_aliases": ["nope", "kkdk"]})

    assert len(postings) == 3
    [error] = drain_errors()["hr_manager"]
    assert "nope" in error


@responses.activate
def test_a_failed_transaction_status_is_an_error():
    responses.add(responses.GET, _KKDK, json={"TransactionStatus": {"StatusCode": 1, "Description": "broken"}, "Items": []})

    drain_errors()
    assert hr_manager.scrape({"hr_manager_aliases": ["kkdk"]}) == []
    assert "broken" in drain_errors()["hr_manager"][0]


def test_no_aliases_no_request():
    assert hr_manager.scrape({}) == []


@responses.activate
def test_probe_reads_page_one_of_the_first_alias():
    responses.add(responses.GET, re.compile(re.escape(_KKDK)), body=_fx("kkdk_page1.json"))

    result = hr_manager.probe({"hr_manager_aliases": ["kkdk", "regionh"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 2
    assert len(responses.calls) == 1


@responses.activate
def test_probe_drift_without_an_items_list():
    responses.add(responses.GET, re.compile(re.escape(_KKDK)), body=json.dumps({"unexpected": True}))

    result = hr_manager.probe({"hr_manager_aliases": ["kkdk"]})

    assert result["structure_ok"] is False


def test_probe_none_without_aliases():
    assert hr_manager.probe({}) is None


@responses.activate
def test_a_posting_keeps_its_own_department_name_whatever_the_followed_names_say():
    """A portal serves many employers (hospitals, agencies): the name is per posting, deliberately."""
    _pages()

    postings = hr_manager.scrape({"hr_manager_aliases": ["kkdk"],
                                  "_names": {"hr_manager_aliases": {"kkdk": "KK"}}})

    assert postings[0]["company"] == "Københavns Kommune"


@responses.activate
def test_scrape_drops_positions_in_another_country_and_counts_them():
    from door.scrapers import drain_non_local
    page1 = json.loads(_fx("kkdk_page1.json"))
    page1["Items"][0]["Department"]["City"] = "London, UK"
    responses.add(responses.GET, _KKDK, body=json.dumps(page1), match=[__import__("responses").matchers.query_param_matcher(
        {"take": "2", "skip": "0", "incads": "true"})])
    responses.add(responses.GET, _KKDK, body=_fx("kkdk_page2.json"), match=[__import__("responses").matchers.query_param_matcher(
        {"take": "2", "skip": "2", "incads": "true"})])
    drain_non_local("hr_manager")

    postings = hr_manager.scrape({"hr_manager_aliases": ["kkdk"], "location": "Copenhagen, Denmark"})

    assert [p["platform_id"] for p in postings] == ["kkdk-216557", "kkdk-216495"]
    assert drain_non_local("hr_manager") == 1
