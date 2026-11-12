"""Unit tests for liveness.py — classify_response and verify_liveness.

All tests are offline; network calls are mocked with `responses` or
monkeypatched. Pure function tests require no mocking.
"""

import json
from pathlib import Path

import responses as responses_lib

import door.core.liveness as liveness


# ---------------------------------------------------------------------------
# classify_response — pure function tests (no network)
# ---------------------------------------------------------------------------


def test_classify_200_clean_body_is_live():
    assert liveness.classify_response(200, "Welcome to our careers page!", {}) == "live"


def test_classify_200_position_has_been_filled_case_insensitive():
    assert liveness.classify_response(200, "Position Has Been Filled", {}) == "expired"


def test_classify_404_is_expired():
    assert liveness.classify_response(404, "", {}) == "expired"


def test_classify_403_is_indeterminate():
    assert liveness.classify_response(403, "", {}) == "indeterminate"


def test_classify_500_is_indeterminate():
    assert liveness.classify_response(500, "Internal Server Error", {}) == "indeterminate"


def test_classify_custom_config_phrase_expired():
    config = {"liveness_expiry_phrases": ["job closed"]}
    assert liveness.classify_response(200, "Sorry, this job closed last week.", config) == "expired"


# ---------------------------------------------------------------------------
# verify_liveness — integration tests using @responses.activate + tmp_path
# ---------------------------------------------------------------------------


def _write_posting(path: Path, url: str = "https://example.com/jobs/123") -> dict:
    """Write a minimal posting JSON file and return the dict."""
    data = {
        "id": "test-acme-job",
        "title": "Test Job",
        "company": "Acme",
        "location": "Copenhagen",
        "url": url,
        "description": "A test job.",
        "source": "jobindex",
        "scraped_at": "2026-06-15T00:00:00Z",
    }
    path.write_text(json.dumps(data))
    return data


_JOB_URL = "https://example.com/jobs/123"


@responses_lib.activate
def test_verify_liveness_live_posting_kept_and_status_written(tmp_path, monkeypatch):
    """A 200 OK clean response keeps the posting and writes liveness_status='live'."""
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: None)

    path = tmp_path / "posting.json"
    _write_posting(path, _JOB_URL)
    responses_lib.add(responses_lib.GET, _JOB_URL, body="Welcome to our jobs page!", status=200)

    result = liveness.verify_liveness([path], {})

    assert path in result
    data = json.loads(path.read_text())
    assert data["liveness_status"] == "live"


@responses_lib.activate
def test_verify_liveness_404_excluded_and_marked_expired(tmp_path, monkeypatch):
    """A 404 response excludes the posting and writes liveness_status='expired', score=0.0."""
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: None)

    path = tmp_path / "posting.json"
    _write_posting(path, _JOB_URL)
    responses_lib.add(responses_lib.GET, _JOB_URL, status=404)

    result = liveness.verify_liveness([path], {})

    assert path not in result
    data = json.loads(path.read_text())
    assert data["liveness_status"] == "expired"
    assert data["score"] == 0.0
    assert data["score_reason"] == "expired"


@responses_lib.activate
def test_verify_liveness_403_kept_as_indeterminate(tmp_path, monkeypatch):
    """A 403 response keeps the posting with liveness_status='indeterminate'."""
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: None)

    path = tmp_path / "posting.json"
    _write_posting(path, _JOB_URL)
    responses_lib.add(responses_lib.GET, _JOB_URL, status=403)

    result = liveness.verify_liveness([path], {})

    assert path in result
    data = json.loads(path.read_text())
    assert data["liveness_status"] == "indeterminate"


@responses_lib.activate
def test_verify_liveness_network_error_kept_as_indeterminate(tmp_path, monkeypatch):
    """A network-level exception keeps the posting as indeterminate."""
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: None)

    path = tmp_path / "posting.json"
    _write_posting(path, _JOB_URL)
    responses_lib.add(responses_lib.GET, _JOB_URL, body=ConnectionError("refused"))

    result = liveness.verify_liveness([path], {})

    assert path in result
    data = json.loads(path.read_text())
    assert data["liveness_status"] == "indeterminate"


def test_verify_liveness_empty_paths_returns_empty():
    assert liveness.verify_liveness([], {}) == []


@responses_lib.activate
def test_verify_liveness_no_url_kept_as_indeterminate(tmp_path, monkeypatch):
    """A posting JSON without a 'url' key is kept with indeterminate status."""
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: None)

    data = {
        "id": "test-no-url",
        "title": "No URL Job",
        "company": "Acme",
        "source": "jobindex",
        "scraped_at": "2026-06-15T00:00:00Z",
    }
    path = tmp_path / "no_url.json"
    path.write_text(json.dumps(data))

    result = liveness.verify_liveness([path], {})

    assert path in result
    saved = json.loads(path.read_text())
    assert saved["liveness_status"] == "indeterminate"


@responses_lib.activate
def test_verify_liveness_jitter_delay_called(tmp_path, monkeypatch):
    """Sleep is called at least once per posting to enforce jitter delay."""
    sleeps = []
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: sleeps.append(s))

    path = tmp_path / "posting.json"
    _write_posting(path, _JOB_URL)
    responses_lib.add(responses_lib.GET, _JOB_URL, body="OK", status=200)

    liveness.verify_liveness([path], {})

    assert len(sleeps) >= 1


@responses_lib.activate
def test_verify_liveness_reports_each_posting_and_prints_nothing(tmp_path, monkeypatch, progress_events, capsys):
    """One progress event per posting (i/n, stage liveness); nothing on stdout."""
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: None)

    live, dead = tmp_path / "live.json", tmp_path / "dead.json"
    _write_posting(live, _JOB_URL)
    _write_posting(dead, "https://example.com/jobs/gone")
    responses_lib.add(responses_lib.GET, _JOB_URL, body="Welcome!", status=200)
    responses_lib.add(responses_lib.GET, "https://example.com/jobs/gone", status=404)

    liveness.verify_liveness([live, dead], {})

    assert [(e.message, e.done, e.total, e.stage) for e in progress_events] == [
        ("liveness: live", 1, 2, "liveness"),
        ("liveness: expired", 2, 2, "liveness"),
    ]
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
