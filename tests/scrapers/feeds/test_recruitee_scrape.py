"""Fixture tests for the Recruitee careers API (issue #231): Famly's live offers, trimmed."""

import pytest
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.feeds import recruitee
from paths import TESTS_DIR

_OFFERS = "https://famly.recruitee.com/api/offers/"


def _fx() -> str:
    return (TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "recruitee" / "famly.json").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_maps_every_published_offer():
    responses.add(responses.GET, _OFFERS, body=_fx())

    postings = recruitee.scrape({"recruitee_companies": ["famly"]})

    assert len(postings) == 2
    first = postings[0]
    JobPosting.model_validate(first)
    assert first["title"] == "Senior Design System Engineer"
    assert first["company"] == "Famly"
    assert first["platform_id"] == "2743487"
    assert first["location"] == "Copenhagen, Hovedstaden, Denmark"
    assert first["url"] == "https://famly.recruitee.com/o/senior-design-system-engineer"
    assert first["apply_url"] == "https://famly.recruitee.com/o/senior-design-system-engineer/c/new"
    assert first["posted_at"].startswith("2026-09-11T13:08:03")
    assert first["description"].startswith("Design for the people in the tiny chairs")
    assert "You’ll thrive in this role if you" in first["description"]  # requirements included
    assert "<" not in first["description"]
    assert first["source"] == "recruitee"


@responses.activate
def test_an_unknown_company_is_a_recorded_error():
    responses.add(responses.GET, "https://nope.recruitee.com/api/offers/", status=404)
    responses.add(responses.GET, _OFFERS, body=_fx())

    drain_errors()
    assert len(recruitee.scrape({"recruitee_companies": ["nope", "famly"]})) == 2
    assert "nope" in drain_errors()["recruitee"][0]


@responses.activate
def test_a_custom_careers_host_is_read_like_a_slug():
    responses.add(responses.GET, "https://careers.famly.co/api/offers/", body=_fx())

    assert len(recruitee.scrape({"recruitee_companies": ["careers.famly.co"]})) == 2


def test_no_companies_no_request():
    assert recruitee.scrape({}) == []
    assert recruitee.probe({}) is None


@responses.activate
def test_probe_reads_the_first_company():
    responses.add(responses.GET, _OFFERS, body=_fx())

    result = recruitee.probe({"recruitee_companies": ["famly", "other"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 2


@responses.activate
def test_probe_drift_without_an_offers_list():
    responses.add(responses.GET, _OFFERS, json={"jobs": []})

    assert recruitee.probe({"recruitee_companies": ["famly"]})["structure_ok"] is False


@responses.activate
def test_the_followed_name_wins():
    responses.add(responses.GET, _OFFERS, body=_fx())

    postings = recruitee.scrape({"recruitee_companies": ["https://Famly.recruitee.com/"],
                                 "_names": {"recruitee_companies": {"famly.recruitee.com": "Famly ApS"}}})

    assert postings and {p["company"] for p in postings} == {"Famly ApS"}
    assert all(p["id"].startswith("recruitee.") for p in postings)


@responses.activate
def test_without_a_name_map_the_feed_name_is_the_fallback():
    responses.add(responses.GET, _OFFERS, body=_fx())

    assert {p["company"] for p in recruitee.scrape({"recruitee_companies": ["famly"]})} == {"Famly"}


@responses.activate
def test_scrape_drops_offers_in_another_country_but_keeps_remote_ones():
    import json
    from door.scrapers import drain_non_local
    data = json.loads(_fx())
    data["offers"][0].update(location="London, UK", remote=False)
    data["offers"][1].update(location="Europe", remote=True)
    data["offers"].append({**data["offers"][0], "id": 99999, "guid": "zzz", "slug": "bud", "location": "Budapest, Hungary",
                           "careers_url": "https://famly.recruitee.com/o/bud"})
    responses.add(responses.GET, _OFFERS, body=json.dumps(data))
    drain_non_local("recruitee")

    postings = recruitee.scrape({"recruitee_companies": ["famly"], "location": "Budapest, Hungary"})

    assert [p["location"] for p in postings] == ["Remote, Europe", "Budapest, Hungary"]
    assert drain_non_local("recruitee") == 1
