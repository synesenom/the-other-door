"""Fixture tests for the full The Hub scrape() path — Nuxt SSR over plain HTTP.

The Hub renders `window.__NUXT__=(function(a,b,…){return {…}}(…))` into its HTML.
HTTP is mocked with `responses`: three pages saved from the live site
(`listing_real.html`, `detail_lunar_real.html`, `listing_empty_real.html`, trimmed to
the script and the keys read, the ad text rewritten) and pages built here around the saved payloads (`listing_page*.json`,
`detail_*.json`) for pagination, dedup and the failure paths. No network, no browser.
"""

import json
from pathlib import Path

import pytest
import responses
import requests

from door.core.models import JobPosting
from door.scrapers import drain_answered, drain_errors
from door.scrapers.boards import thehub

_FIX = Path(__file__).parent / "fixtures" / "thehub"
_CFG = {"role_targets": ["data scientist"], "location": "Copenhagen"}
_LUNAR = "6a8e2cfa6f40d9d0b631fedd"


def _fx(name: str) -> dict:
    return json.loads((_FIX / name).read_text(encoding="utf-8"))


def _html(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


def _nuxt_page(state: dict) -> str:
    """A page in the shape the site serves: an IIFE returning the state."""
    return ("<html><body><script>window.__NUXT__=(function(a){return {state:a}}("
            + json.dumps(state) + "));</script></body></html>")


def _listing(jobs_obj: dict) -> str:
    return _nuxt_page({"jobs": {"jobs": jobs_obj}})


def _detail(job_obj: dict | None) -> str:
    return _nuxt_page({"jobs": {"job": job_obj}})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _serve(url: str, body: str | None = None, **kw) -> None:
    responses.add(responses.GET, url, body=body, **kw)


@responses.activate
def test_scrape_paginates_dedups_and_fetches_details():
    _serve(thehub._listing_url("data scientist", "DK", 1), _listing(_fx("listing_page1.json")))
    _serve(thehub._listing_url("data scientist", "DK", 2), _listing(_fx("listing_page2.json")))
    _serve(thehub._job_url("6aa1f3cc961a30471ccb36b8"), _detail(_fx("detail_flatpay.json")))
    envira = thehub._job_url("6a918622eb2ed4dae7b2f5fa")
    _serve(envira, _detail({}))  # missing/empty job -> skipped
    _serve(thehub._job_url(_LUNAR), _detail(_fx("detail_lunar.json")))

    drain_errors()
    postings = thehub.scrape(_CFG)

    # Flatpay deduped across page1/page2, Envira detail empty -> skipped, Lunar OK.
    assert [p["platform_id"] for p in postings] == ["6aa1f3cc961a30471ccb36b8", _LUNAR]
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "thehub"
        assert p["title"] and p["company"] and p["url"]
        assert "<" not in p["description"]

    by_id = {p["platform_id"]: p for p in postings}
    flatpay = by_id["6aa1f3cc961a30471ccb36b8"]
    assert flatpay["title"] == "Data Scientist"
    assert flatpay["company"] == "Flatpay"
    assert flatpay["location"] == "Copenhagen, Denmark"
    assert flatpay["url"] == "https://thehub.io/jobs/6aa1f3cc961a30471ccb36b8"
    assert flatpay["id"] == "thehub.6aa1f3cc961a30471ccb36b8"
    assert flatpay["posted_at"].startswith("2026-09-11")
    # The ad's `link` is the company's own job page: where to apply.
    assert flatpay["apply_type"] == "external"
    assert flatpay["apply_url"] == "https://jobs.flatpay.com/jobs/8331954"

    lunar = by_id[_LUNAR]
    assert lunar["company"] == "Lunar"
    assert lunar["location"] == "Aarhus, Denmark"
    assert lunar["posted_at"] is None  # real doc has null publishedAt

    assert any(envira in msg for msg in drain_errors()["thehub"])


@responses.activate
def test_scrape_reads_the_pages_saved_from_the_live_site():
    """The real `window.__NUXT__` IIFE of a listing and of a job page, evaluated whole."""
    listing = thehub._listing_url("data scientist", "DK", 1)
    _serve(listing, _html("listing_real.html"))
    ids = [d["id"] for d in thehub._nuxt_state(_html("listing_real.html"), ("state", "jobs", "jobs"))["docs"]]
    assert len(ids) == 8 and _LUNAR in ids
    for job_id in ids:
        # Only Lunar's page was saved; the others come back empty and are skipped.
        _serve(thehub._job_url(job_id), _html("detail_lunar_real.html") if job_id == _LUNAR else _detail({}))

    drain_errors()
    postings = thehub.scrape(_CFG)

    [lunar] = postings
    JobPosting.model_validate(lunar)
    assert lunar["platform_id"] == _LUNAR
    assert lunar["title"] == "(Senior) Data Scientist"
    assert lunar["company"] == "Lunar"
    assert lunar["apply_url"] == "https://jobs.lunar.app/jobs/8264790"
    assert lunar["posted_at"].startswith("2026-10-06")
    assert lunar["description"] and "<" not in lunar["description"]
    assert len(drain_errors()["thehub"]) == 7


@responses.activate
def test_scrape_empty_search_returns_no_postings():
    _serve(thehub._listing_url("zzzqqq", "DK", 1), _html("listing_empty_real.html"))
    drain_errors()
    drain_answered("thehub")
    assert thehub.scrape({"role_targets": ["zzzqqq"], "location": "Copenhagen"}) == []
    assert drain_errors() == {}
    assert drain_answered("thehub") is True


@responses.activate
def test_an_empty_listing_scrapes_to_nothing(monkeypatch):
    _serve(thehub._listing_url("data scientist", "DK", 1), _listing(_fx("listing_empty.json")))
    assert thehub.scrape(_CFG) == []


@responses.activate
def test_scrape_listing_http_error_breaks_keyword_and_records_error(progress_events, capsys):
    _serve(thehub._listing_url("data scientist", "DK", 1), "nope", status=404)

    drain_errors()
    assert thehub.scrape(_CFG) == []

    assert any("data scientist" in msg for msg in drain_errors()["thehub"])
    assert any("listing error" in e.message for e in progress_events)
    assert capsys.readouterr().out == ""


@responses.activate
def test_scrape_listing_without_nuxt_records_error(progress_events):
    _serve(thehub._listing_url("data scientist", "DK", 1), "<html><body>Just a moment...</body></html>")

    drain_errors()
    assert thehub.scrape(_CFG) == []

    assert any("listing error" in e.message and "__NUXT__" in e.message for e in progress_events)
    assert drain_errors()["thehub"]


@responses.activate
def test_scrape_listing_whose_script_fails_to_evaluate_records_error(progress_events):
    _serve(thehub._listing_url("data scientist", "DK", 1),
           "<script>window.__NUXT__=(function(a){return a.nope.x}(1));</script>")

    drain_errors()
    drain_answered("thehub")
    assert thehub.scrape(_CFG) == []

    assert any("listing error" in e.message for e in progress_events)
    assert drain_errors()["thehub"]
    assert drain_answered("thehub") is False


@responses.activate
def test_scrape_malformed_listing_payload_records_error(progress_events):
    """window.__NUXT__.state.jobs.jobs missing/malformed -> treated as an error."""
    _serve(thehub._listing_url("data scientist", "DK", 1), _nuxt_page({"jobs": {}}))

    drain_errors()
    assert thehub.scrape(_CFG) == []

    assert any("listing error" in e.message for e in progress_events)
    assert drain_errors()["thehub"]


@responses.activate
def test_scrape_detail_http_error_skips_job_but_continues(progress_events, capsys):
    """A failing detail request for one job doesn't abort the others."""
    envira = thehub._job_url("6a918622eb2ed4dae7b2f5fa")
    _serve(thehub._listing_url("data scientist", "DK", 1), _listing(_fx("listing_page1.json")))
    _serve(thehub._job_url("6aa1f3cc961a30471ccb36b8"), _detail(_fx("detail_flatpay.json")))
    _serve(envira, "boom", status=500)

    drain_errors()
    postings = thehub.scrape(_CFG)

    assert [p["platform_id"] for p in postings] == ["6aa1f3cc961a30471ccb36b8"]
    assert any(envira in msg for msg in drain_errors()["thehub"])
    assert any(envira in e.message for e in progress_events)
    assert capsys.readouterr().out == ""


@responses.activate
def test_scrape_detail_empty_payload_is_reported_and_recorded(progress_events):
    _serve(thehub._listing_url("data scientist", "DK", 1), _listing(_fx("listing_page1.json")))
    _serve(thehub._job_url("6aa1f3cc961a30471ccb36b8"), _detail(None))
    _serve(thehub._job_url("6a918622eb2ed4dae7b2f5fa"), _detail(None))

    drain_errors()
    assert thehub.scrape(_CFG) == []

    assert any("empty/missing job payload" in e.message for e in progress_events)
    assert any("empty/missing job payload" in m for m in drain_errors()["thehub"])


@responses.activate
def test_scrape_uses_search_keywords_over_role_targets():
    first = thehub._listing_url("data science lead", "DK", 1)
    second = thehub._listing_url("head of data science", "DK", 1)
    _serve(first, _listing(_fx("listing_empty.json")))
    _serve(second, _listing(_fx("listing_empty.json")))

    thehub.scrape({
        "role_targets": ["lead data scientist"],
        "search_keywords": ["data science lead", "head of data science"],
        "location": "Copenhagen",
    })

    assert [c.request.url for c in responses.calls] == [first, second]


# --------------------------------------------------------------------------- #
# probe (issue #178)
# --------------------------------------------------------------------------- #

def _probe_url():
    return thehub._listing_url("data scientist", "DK", 1)


@responses.activate
def test_probe_ok_maps_listing_without_detail_fetches():
    _serve(_probe_url(), _html("listing_real.html"))
    drain_errors()
    result = thehub.probe(_CFG)
    assert result["structure_ok"] is True and result["ext"] == "html"
    assert len(result["postings"]) == 8
    for p in result["postings"]:
        JobPosting.model_validate(p)
    assert [c.request.url for c in responses.calls] == [_probe_url()]  # page 1 only, no detail pages
    assert "window.__NUXT__" in result["raw"]
    assert drain_errors() == {}


@responses.activate
def test_probe_drift_when_listing_key_is_gone():
    _serve(_probe_url(), _nuxt_page({"jobs": {}}))
    result = thehub.probe(_CFG)
    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")


@responses.activate
def test_probe_page_without_nuxt_is_drift():
    _serve(_probe_url(), "<html>hello</html>")
    result = thehub.probe(_CFG)
    assert result["structure_ok"] is False and "__NUXT__" in result["reason"]


@responses.activate
def test_probe_forbidden_is_a_wall():
    _serve(_probe_url(), "Just a moment...", status=403)
    assert thehub.probe(_CFG)["wall"] is True


@responses.activate
def test_probe_connection_error_is_unreachable():
    _serve(_probe_url(), body=requests.exceptions.ConnectionError("down"))
    assert thehub.probe(_CFG)["unreachable"] is True


def test_probe_without_keywords_is_none():
    assert thehub.probe({"location": "Copenhagen"}) is None


@pytest.mark.usefixtures("obey_robots")
@pytest.mark.real_robots
@responses.activate
def test_a_page_robots_disallows_is_never_loaded():
    """Every page is checked against thehub.io/robots.txt before it is fetched (#226)."""
    responses.add(responses.GET, "https://thehub.io/robots.txt", body="User-agent: *\nDisallow: /jobs\n")

    drain_errors()
    assert thehub.scrape(_CFG) == []

    assert [c.request.url for c in responses.calls] == ["https://thehub.io/robots.txt"]
    [error] = drain_errors()["thehub"]
    assert "robots.txt disallows" in error
