"""Fixture tests for the full Greenhouse scrape() path (fixture layer).

HTTP is mocked with ``responses`` from saved API payloads captured from the
real Greenhouse boards API. No network access during these tests.
"""

import json
from pathlib import Path

import pytest
import responses as responses_lib

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.feeds import greenhouse

_FIX = Path(__file__).parent / "fixtures" / "greenhouse"

_JOBS_URL = f"{greenhouse._API_BASE}/acme/jobs"


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses_lib.activate
def test_scrape_maps_fields_and_strips_html():
    """Scrape with two real jobs: verify field mapping, HTML entity stripping, model validity."""
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=_fx("jobs_page.json"),
                      content_type="application/json")

    postings = greenhouse.scrape({"greenhouse_boards": ["acme"]})

    assert len(postings) == 2

    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "greenhouse"
        assert p["company"] == "Greenhouse"  # from company_name field in real response
        assert p["title"] and p["url"]
        assert "<" not in p["description"]   # HTML tags stripped
        assert "&lt;" not in p["description"]  # HTML entities also resolved

    by_id = {p["platform_id"]: p for p in postings}

    csm = by_id["7982460"]
    assert csm["title"] == "Customer Success Manager, Mid-Market"
    assert csm["location"] == "Anywhere in the United States"
    assert csm["url"] == "https://job-boards.greenhouse.io/greenhouse/jobs/7982460?gh_jid=7982460"
    assert csm["posted_at"] is not None
    assert csm["id"] == "greenhouse." + csm["platform_id"]
    assert csm["apply_type"] == "external"
    assert csm["apply_url"] == csm["url"]

    gtm = by_id["7982414"]
    assert gtm["title"] == "GTM Engineer"
    assert gtm["location"] == "Ontario"
    assert gtm["apply_type"] == "external"
    assert gtm["apply_url"] == gtm["url"]


@responses_lib.activate
def test_scrape_empty_board_returns_no_postings(capsys, progress_events):
    """A board with no jobs prints a message and returns an empty list."""
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=_fx("jobs_empty.json"),
                      content_type="application/json")

    postings = greenhouse.scrape({"greenhouse_boards": ["acme"]})

    assert postings == []
    assert any("0 results" in e.message for e in progress_events)
    assert capsys.readouterr().out == ""


@responses_lib.activate
def test_scrape_http_error_is_recorded(progress_events):
    """An HTTP 500 is swallowed (scrape returns []) and recorded (issue #132)."""
    responses_lib.add(responses_lib.GET, _JOBS_URL, status=500)

    drain_errors()
    assert greenhouse.scrape({"greenhouse_boards": ["acme"]}) == []
    assert any("error fetching 'acme'" in e.message for e in progress_events)
    errors = drain_errors()
    assert "greenhouse" in errors
    assert len(errors["greenhouse"]) == 1
    assert "acme" in errors["greenhouse"][0]


@responses_lib.activate
def test_scrape_deduplicates_jobs():
    """If the same platform_id appears in multiple boards, it is deduplicated."""
    jobs_url2 = f"{greenhouse._API_BASE}/contoso/jobs"

    # Board 1: acme with real jobs 7982460, 7982414
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=_fx("jobs_page.json"),
                      content_type="application/json")

    # Board 2: contoso with same job id 7982460 (cross-board dedup)
    contoso_jobs = json.dumps({
        "jobs": [{"id": 7982460, "title": "Duplicate Job", "updated_at": "2026-05-01T12:00:00Z",
                  "location": {"name": "Remote"}, "absolute_url": "https://example.com/dup",
                  "content": "", "company_name": "Contoso"}],
        "meta": {"total": 1}
    })
    responses_lib.add(responses_lib.GET, jobs_url2, body=contoso_jobs,
                      content_type="application/json")

    postings = greenhouse.scrape({"greenhouse_boards": ["acme", "contoso"]})

    ids = [p["platform_id"] for p in postings]
    assert ids.count("7982460") == 1
    assert len(postings) == 2  # 7982460 + 7982414 from acme; 7982460 from contoso deduped


# --------------------------------------------------------------------------- #
# probe (issue #178)
# --------------------------------------------------------------------------- #

_PROBE_CFG = {"greenhouse_boards": ["acme", "other"]}


@responses_lib.activate
def test_probe_ok_uses_the_first_board_only():
    import json  # noqa: F401

    body = _fx("jobs_page.json")
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=body)
    drain_errors()
    result = greenhouse.probe(_PROBE_CFG)
    assert result["structure_ok"] is True and result["ext"] == "json" and result["raw"] == body
    assert result["postings"]
    for p in result["postings"]:
        JobPosting.model_validate(p)
    assert [c.request.url.split("?")[0] for c in responses_lib.calls if "robots" not in c.request.url] == [_JOBS_URL]
    assert drain_errors() == {}


@responses_lib.activate
def test_probe_drift_when_structure_is_broken():
    import json  # noqa: F401

    responses_lib.add(responses_lib.GET, _JOBS_URL, body=json.dumps({"unexpected": []}))
    result = greenhouse.probe(_PROBE_CFG)
    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")




@responses_lib.activate
def test_the_followed_name_wins():
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=_fx("jobs_page.json"), content_type="application/json")
    entry = "https://boards.greenhouse.io/acme"
    config = {"greenhouse_boards": [entry],
              "_names": {"greenhouse_boards": {"boards.greenhouse.io/acme": "Acme A/S"}}}

    postings = greenhouse.scrape(config)

    assert postings and {p["company"] for p in postings} == {"Acme A/S"}
    assert all(p["id"].startswith("greenhouse.") for p in postings)


@responses_lib.activate
def test_without_a_name_map_the_feed_name_is_the_fallback():
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=_fx("jobs_page.json"), content_type="application/json")

    postings = greenhouse.scrape({"greenhouse_boards": ["https://boards.greenhouse.io/acme"]})

    assert {p["company"] for p in postings} == {"Greenhouse"}


_HU = {"location": "Budapest, Hungary"}


@responses_lib.activate
def test_scrape_drops_postings_in_another_country_and_counts_them():
    from door.scrapers import drain_non_local
    data = json.loads(_fx("jobs_page.json"))
    data["jobs"][0]["location"]["name"] = "London, UK"
    data["jobs"][1]["location"]["name"] = "Budapest, Hungary"
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=json.dumps(data), content_type="application/json")
    drain_non_local("greenhouse")

    postings = greenhouse.scrape({"greenhouse_boards": ["acme"], **_HU})

    assert [p["location"] for p in postings] == ["Budapest, Hungary"]
    assert drain_non_local("greenhouse") == 1


@responses_lib.activate
def test_scrape_keeps_everything_without_a_profile_country():
    from door.scrapers import drain_non_local
    data = json.loads(_fx("jobs_page.json"))
    data["jobs"][0]["location"]["name"] = "London, UK"
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=json.dumps(data), content_type="application/json")
    drain_non_local("greenhouse")

    assert len(greenhouse.scrape({"greenhouse_boards": ["acme"]})) == 2
    assert drain_non_local("greenhouse") == 0
