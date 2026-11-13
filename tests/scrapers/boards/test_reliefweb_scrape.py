"""Fixture tests for the full ReliefWeb scrape() path: one RSS feed per keyword, HTTP mocked with `responses`
from a saved feed (trimmed to what the parser reads, the ad text rewritten)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import responses

from door.core.models import JobPosting
from door.scrapers import drain_answered, drain_errors, drain_non_local
from door.scrapers.boards import reliefweb

_FIX = Path(__file__).parent / "fixtures" / "reliefweb"
_CFG = {"search_keywords": ["monitoring evaluation"], "role_targets": ["MEL officer"], "location": "Copenhagen"}
# No country the data knows: nothing is dropped as non-local, so every job in the feed comes back.
_ANY = {**_CFG, "location": ""}


def _xml(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    drain_errors("reliefweb"), drain_non_local("reliefweb"), drain_answered("reliefweb")


def _serve(keyword="monitoring evaluation", body=None, **kw):
    responses.add(responses.GET, reliefweb._feed_url(keyword), body=body if body is not None else _xml("mel_page.xml"), **kw)


@responses.activate
def test_a_local_profile_gets_local_unspecified_and_home_based_jobs_only():
    _serve()
    postings = reliefweb.scrape(_CFG)
    by_id = {p["platform_id"]: p for p in postings}
    assert set(by_id) == {"4235500", "4235600", "4235800"}
    assert drain_non_local("reliefweb") == 3
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "reliefweb" and p["id"] == f"reliefweb.{p['platform_id']}"
        assert p["title"] and p["company"] and p["url"].startswith("https://reliefweb.int/job/")
    assert by_id["4235500"]["location"] == ""
    assert by_id["4235600"]["location"] == "Home-based, Guatemala"
    assert by_id["4235800"]["location"] == "Denmark"
    assert by_id["4235800"]["company"] == "Danish Red Cross"


@responses.activate
def test_known_ids_and_old_jobs_are_skipped():
    _serve()
    since = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    postings = reliefweb.scrape(_ANY, known_ids=frozenset({"4236426"}), since=since)
    # not the known Nepal one; not the ones posted before 28 Oct 12:00 (Kenya 26th, Guatemala 27th, one-health is 30th)
    assert {p["platform_id"] for p in postings} == {"4235500", "4235700"}


@responses.activate
def test_each_keyword_is_one_feed_and_a_job_in_two_feeds_counts_once():
    _serve("monitoring evaluation")
    _serve("mel officer")
    postings = reliefweb.scrape({**_ANY, "search_keywords": ["monitoring evaluation", "mel officer"]})
    assert len(postings) == 6 and len(responses.calls) == 2


@responses.activate
def test_a_failing_feed_is_recorded_and_the_next_keyword_still_runs():
    _serve("monitoring evaluation", status=500)
    _serve("mel officer")
    postings = reliefweb.scrape({**_ANY, "search_keywords": ["monitoring evaluation", "mel officer"]})
    assert len(postings) == 6
    assert any("monitoring evaluation" in e for e in drain_errors("reliefweb").get("reliefweb", []))


@responses.activate
def test_a_page_that_is_not_a_feed_is_an_error():
    _serve(body="<html><body>maintenance</body></html>")
    assert reliefweb.scrape(_CFG) == []
    assert drain_errors("reliefweb").get("reliefweb")
    assert drain_answered("reliefweb") is False


@responses.activate
def test_an_empty_challenge_answer_is_retried_once_after_a_pause(monkeypatch):
    # The site's load balancer sometimes answers 202 with no body instead of the feed (#537).
    pauses = []
    monkeypatch.setattr(reliefweb.time, "sleep", lambda s: pauses.append(s))
    _serve(body="", status=202)
    _serve()
    postings = reliefweb.scrape(_ANY)
    assert len(postings) == 6 and len(responses.calls) == 2
    assert max(pauses) >= 10
    assert not drain_errors("reliefweb").get("reliefweb")


@responses.activate
def test_an_empty_answer_that_stays_empty_is_a_clear_error():
    _serve(body="", status=202)
    _serve(body="", status=202)
    assert reliefweb.scrape(_CFG) == []
    errors = drain_errors("reliefweb").get("reliefweb")
    assert errors and "empty" in errors[0] and "202" in errors[0]


@responses.activate
def test_probe_reports_an_empty_answer_as_not_ok():
    _serve(body="", status=202)
    result = reliefweb.probe(_CFG)
    assert result is not None and not result.get("structure_ok")
    assert "empty" in (result.get("reason") or "") or result.get("wall") or result.get("error")


@responses.activate
def test_an_empty_feed_is_quiet():
    _serve(body=_xml("empty.xml"))
    assert reliefweb.scrape(_CFG) == []
    assert not drain_errors("reliefweb").get("reliefweb")
    assert drain_answered("reliefweb") is True


@responses.activate
def test_probe_reads_the_first_feed():
    _serve()
    result = reliefweb.probe(_CFG)
    assert result is not None and result["structure_ok"] and len(result["postings"]) == 6


def test_probe_needs_a_keyword():
    assert reliefweb.probe({"location": "Copenhagen"}) is None
