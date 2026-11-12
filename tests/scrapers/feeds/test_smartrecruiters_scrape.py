"""Fixture tests for the SmartRecruiters postings API: Inter IKEA Group's live postings, trimmed."""

import json

import pytest
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.feeds import smartrecruiters
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "smartrecruiters"
_API = "https://api.smartrecruiters.com/v1/companies/interikeagroup/postings"
_IDS = ["744000155037995", "744000154989708", "744000154955779"]


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _mock_all():
    responses.add(responses.GET, _API, body=_fx("interikeagroup_list.json"))
    for pid in _IDS:
        responses.add(responses.GET, f"{_API}/{pid}", body=_fx(f"interikeagroup_{pid}.json"))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_maps_every_posting_with_its_detail():
    _mock_all()

    postings = smartrecruiters.scrape({"smartrecruiters_companies": ["interikeagroup"]})

    assert len(postings) == 3
    first = postings[0]
    JobPosting.model_validate(first)
    assert first["title"] == "Customs Analyst"
    assert first["company"] == "Inter IKEA Group"
    assert first["platform_id"] == "744000155037995"
    assert first["location"] == "Älmhult, Sweden"
    assert first["url"] == "https://jobs.smartrecruiters.com/InterIKEAGroup/744000155037995-customs-analyst"
    assert first["apply_url"].startswith(first["url"])
    assert first["posted_at"].startswith("2026-10-12T14:34:44")
    assert first["description"].startswith("Hej Customs Analyst")
    assert "<" not in first["description"]
    assert first["source"] == "smartrecruiters"


@responses.activate
def test_known_ids_skip_the_detail_request():
    responses.add(responses.GET, _API, body=_fx("interikeagroup_list.json"))
    responses.add(responses.GET, f"{_API}/{_IDS[0]}", body=_fx(f"interikeagroup_{_IDS[0]}.json"))

    postings = smartrecruiters.scrape({"smartrecruiters_companies": ["interikeagroup"]},
                                      known_ids=frozenset(_IDS[1:]))

    assert [p["platform_id"] for p in postings] == [_IDS[0]]
    assert len(responses.calls) == 2  # the listing and one detail


@responses.activate
def test_the_listing_is_paged_until_total_found():
    data = json.loads(_fx("interikeagroup_list.json"))
    page1 = {**data, "totalFound": 3, "limit": 2, "content": data["content"][:2]}
    page2 = {**data, "totalFound": 3, "offset": 2, "limit": 2, "content": data["content"][2:]}
    responses.add(responses.GET, _API, body=json.dumps(page1), match=[responses.matchers.query_param_matcher({"limit": "100", "offset": "0"})])
    responses.add(responses.GET, _API, body=json.dumps(page2), match=[responses.matchers.query_param_matcher({"limit": "100", "offset": "2"})])
    for pid in _IDS:
        responses.add(responses.GET, f"{_API}/{pid}", body=_fx(f"interikeagroup_{pid}.json"))

    assert len(smartrecruiters.scrape({"smartrecruiters_companies": ["interikeagroup"]})) == 3


@responses.activate
def test_a_failing_detail_keeps_the_posting_from_the_listing():
    responses.add(responses.GET, _API, body=_fx("interikeagroup_list.json"))
    responses.add(responses.GET, f"{_API}/{_IDS[0]}", status=404)
    for pid in _IDS[1:]:
        responses.add(responses.GET, f"{_API}/{pid}", body=_fx(f"interikeagroup_{pid}.json"))

    drain_errors()
    postings = smartrecruiters.scrape({"smartrecruiters_companies": ["interikeagroup"]})

    assert len(postings) == 3
    assert postings[0]["description"] == ""
    assert postings[0]["url"].endswith("744000155037995")  # built from the company and posting ids
    assert drain_errors()["smartrecruiters"]


@responses.activate
def test_a_failing_listing_is_a_recorded_error():
    responses.add(responses.GET, "https://api.smartrecruiters.com/v1/companies/nope/postings", status=500)
    _mock_all()

    drain_errors()
    assert len(smartrecruiters.scrape({"smartrecruiters_companies": ["nope", "interikeagroup"]})) == 3
    assert "nope" in drain_errors()["smartrecruiters"][0]


def test_scrape_without_companies_is_empty():
    assert smartrecruiters.scrape({}) == []
    assert smartrecruiters.probe({}) is None


@responses.activate
def test_probe_reads_the_listing_only():
    responses.add(responses.GET, _API, body=_fx("interikeagroup_list.json"))

    result = smartrecruiters.probe({"smartrecruiters_companies": ["interikeagroup"]})

    assert result["structure_ok"] is True
    assert len(result["postings"]) == 3
    assert len(responses.calls) == 1


@responses.activate
def test_postings_in_another_country_get_no_detail_request_and_are_counted_non_local():
    from door.scrapers import drain_non_local

    drain_non_local("smartrecruiters")
    listing = json.loads(_fx("interikeagroup_list.json"))
    listing["content"][0]["location"]["country"] = "dk"        # the first one is local
    listing["content"][2]["location"]["remote"] = True          # the Shanghai one is remote: kept
    responses.add(responses.GET, _API, json=listing)
    for pid in (_IDS[0], _IDS[2]):
        responses.add(responses.GET, f"{_API}/{pid}", body=_fx(f"interikeagroup_{pid}.json"))

    postings = smartrecruiters.scrape({"smartrecruiters_companies": ["interikeagroup"], "location": "Copenhagen, Denmark"})

    assert [p["platform_id"] for p in postings] == [_IDS[0], _IDS[2]]
    assert not any(_IDS[1] in c.request.url for c in responses.calls)
    assert drain_non_local("smartrecruiters") == 1


@responses.activate
def test_the_followed_name_wins():
    _mock_all()

    postings = smartrecruiters.scrape({"smartrecruiters_companies": ["https://jobs.smartrecruiters.com/interikeagroup/"],
                                       "_names": {"smartrecruiters_companies": {"jobs.smartrecruiters.com/interikeagroup": "Inter IKEA"}}})

    assert len(postings) == 3 and {p["company"] for p in postings} == {"Inter IKEA"}
    assert all(p["id"].startswith("smartrecruiters.") for p in postings)


@responses.activate
def test_without_a_name_map_the_feed_name_is_the_fallback():
    _mock_all()

    postings = smartrecruiters.scrape({"smartrecruiters_companies": ["interikeagroup"]})

    assert {p["company"] for p in postings} == {"Inter IKEA Group"}
