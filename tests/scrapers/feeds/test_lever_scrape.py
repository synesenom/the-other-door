"""Fixture tests for the full Lever scrape() path (fixture layer).

HTTP is mocked with ``responses`` from saved API payloads. No network.
"""

from pathlib import Path

import pytest
import responses as responses_lib

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.feeds import lever

_FIX = Path(__file__).parent / "fixtures" / "lever"

_POSTINGS_URL = f"{lever._API_BASE}/acme"


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses_lib.activate
def test_scrape_maps_fields():
    """Scrape with two postings: verify field mapping and model validity."""
    responses_lib.add(
        responses_lib.GET,
        _POSTINGS_URL,
        body=_fx("postings.json"),
        content_type="application/json",
    )

    postings = lever.scrape({"lever_companies": ["acme"]})

    assert len(postings) == 2

    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "lever"
        assert p["company"] == "acme"
        assert p["title"] and p["url"]

    by_id = {p["platform_id"]: p for p in postings}

    ds = by_id["abc-123-def-456-ghi"]
    assert ds["title"] == "Senior Data Scientist"
    assert ds["platform_id"] == "abc-123-def-456-ghi"
    assert ds["location"] == "Copenhagen, Denmark"
    assert ds["url"] == "https://jobs.lever.co/acme/abc-123-def-456-ghi"
    assert "talented data scientist" in ds["description"]
    assert ds["id"] == "lever." + ds["platform_id"]
    assert ds["posted_at"] is not None
    assert ds["apply_type"] == "external"
    assert ds["apply_url"] == ds["url"]

    ml = by_id["xyz-789-uvw-012-rst"]
    assert ml["title"] == "ML Engineer"
    assert ml["location"] == "Remote"
    assert "ML infrastructure" in ml["description"]
    assert ml["apply_type"] == "external"
    assert ml["apply_url"] == ml["url"]


@responses_lib.activate
def test_scrape_empty_returns_no_postings(capsys, progress_events):
    """A board with no postings prints a message and returns an empty list."""
    responses_lib.add(
        responses_lib.GET,
        _POSTINGS_URL,
        body=_fx("postings_empty.json"),
        content_type="application/json",
    )

    postings = lever.scrape({"lever_companies": ["acme"]})

    assert postings == []
    assert any("0 results" in e.message for e in progress_events)
    assert capsys.readouterr().out == ""


@responses_lib.activate
def test_scrape_http_error_returns_empty(progress_events):
    """An HTTP 500 from the postings endpoint is swallowed; scrape returns []."""
    responses_lib.add(
        responses_lib.GET,
        _POSTINGS_URL,
        status=500,
    )

    drain_errors()
    postings = lever.scrape({"lever_companies": ["acme"]})
    assert postings == []
    assert any("error fetching 'acme'" in e.message for e in progress_events)

    errors = drain_errors()
    assert "lever" in errors


# --------------------------------------------------------------------------- #
# probe (issue #178)
# --------------------------------------------------------------------------- #

_PROBE_CFG = {"lever_companies": ["acme", "other"]}


@responses_lib.activate
def test_probe_ok_uses_the_first_board_only():
    import json  # noqa: F401

    body = _fx("postings.json")
    responses_lib.add(responses_lib.GET, _POSTINGS_URL, body=body)
    drain_errors()
    result = lever.probe(_PROBE_CFG)
    assert result["structure_ok"] is True and result["ext"] == "json" and result["raw"] == body
    assert result["postings"]
    for p in result["postings"]:
        JobPosting.model_validate(p)
    assert [c.request.url.split("?")[0] for c in responses_lib.calls if "robots" not in c.request.url] == [_POSTINGS_URL]
    assert drain_errors() == {}


@responses_lib.activate
def test_probe_drift_when_structure_is_broken():
    import json  # noqa: F401

    responses_lib.add(responses_lib.GET, _POSTINGS_URL, body=json.dumps({"unexpected": "object"}))
    result = lever.probe(_PROBE_CFG)
    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")




# --------------------------------------------------------------------------- #
# EU host (issue #227)
# --------------------------------------------------------------------------- #

_US = "https://api.lever.co/v0/postings/siteimprove"
_EU = "https://api.eu.lever.co/v0/postings/siteimprove"


@responses_lib.activate
def test_a_company_missing_on_the_us_host_is_read_from_the_eu_host():
    responses_lib.add(responses_lib.GET, _US, status=404, json={"ok": False, "error": "Document not found"})
    responses_lib.add(responses_lib.GET, _EU, body=_fx("eu_siteimprove.json"), content_type="application/json")

    drain_errors()
    postings = lever.scrape({"lever_companies": ["siteimprove"]})

    assert len(postings) == 2 and all(p["url"].startswith("https://jobs.eu.lever.co/siteimprove/") for p in postings)
    assert drain_errors() == {}


@responses_lib.activate
def test_an_eu_board_url_goes_straight_to_the_eu_host():
    responses_lib.add(responses_lib.GET, _EU, body=_fx("eu_siteimprove.json"), content_type="application/json")

    postings = lever.scrape({"lever_companies": ["https://jobs.eu.lever.co/siteimprove"]})

    assert len(postings) == 2
    assert [c.request.url.split("?")[0] for c in responses_lib.calls] == [_EU]


@responses_lib.activate
def test_a_company_on_neither_host_is_an_error():
    responses_lib.add(responses_lib.GET, _US, status=404)
    responses_lib.add(responses_lib.GET, _EU, status=404)

    drain_errors()
    assert lever.scrape({"lever_companies": ["siteimprove"]}) == []
    [error] = drain_errors()["lever"]
    assert "siteimprove" in error


@responses_lib.activate
def test_probe_finds_an_eu_company_too():
    responses_lib.add(responses_lib.GET, _US, status=404)
    responses_lib.add(responses_lib.GET, _EU, body=_fx("eu_siteimprove.json"), content_type="application/json")

    result = lever.probe({"lever_companies": ["siteimprove"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 2


@responses_lib.activate
def test_the_followed_name_wins():
    responses_lib.add(responses_lib.GET, _POSTINGS_URL, body=_fx("postings.json"), content_type="application/json")

    postings = lever.scrape({"lever_companies": ["Acme"], "_names": {"lever_companies": {"acme": "Acme A/S"}}})

    assert postings and {p["company"] for p in postings} == {"Acme A/S"}
    assert all(p["id"].startswith("lever.") for p in postings)


@responses_lib.activate
def test_without_a_name_map_the_slug_is_the_fallback():
    responses_lib.add(responses_lib.GET, _POSTINGS_URL, body=_fx("postings.json"), content_type="application/json")

    assert {p["company"] for p in lever.scrape({"lever_companies": ["acme"]})} == {"acme"}


@responses_lib.activate
def test_scrape_drops_postings_in_another_country_and_counts_them():
    import json
    from door.scrapers import drain_non_local
    data = json.loads(_fx("postings_full.json"))
    data[0]["categories"]["location"] = "London, UK"
    data[1]["categories"]["location"] = "Budapest"
    responses_lib.add(responses_lib.GET, _POSTINGS_URL, body=json.dumps(data), content_type="application/json")
    drain_non_local("lever")

    postings = lever.scrape({"lever_companies": ["acme"], "location": "Budapest, Hungary"})

    assert [p["location"] for p in postings] == ["Budapest"]
    assert drain_non_local("lever") == 1
