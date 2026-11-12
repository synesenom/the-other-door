"""Fixtures for the pipeline step tests: a profile and jobs dir in tmp, and no way out to the network."""

import types

import pytest

from door.core import workspace
from profile_utils import write_config


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    """Detection reads DNS (CNAME and A records); a test that wants an answer patches these."""
    from door.commands import companies as companies_cmd

    monkeypatch.setattr(companies_cmd, "_cname", lambda host: None)
    monkeypatch.setattr(companies_cmd, "_resolves", lambda host: False)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A profile (in Copenhagen) and an empty jobs dir, redirected into tmp."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    write_config(profile_dir, {"role_targets": ["data scientist"], "location": "Copenhagen"})
    jobs_dir = tmp_path / "jobs"
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)
    return types.SimpleNamespace(profile_dir=profile_dir, jobs_dir=jobs_dir)


@pytest.fixture
def scorer(monkeypatch):
    """A stand-in for the Haiku scorer: scores everything it is handed 0.9; returns the list of ids it received."""
    import door.matching.scorer as scorer_mod

    received: list[str] = []

    def score_postings(postings, *, on_result=None, model=None, **kw):
        for p in postings:
            received.append(p["id"])
            on_result(p["id"], {"score": 0.9, "score_reason": "ok", "scored_by": model, "scored_at": "2026-10-13T00:00:00+00:00"})
        return {}, []

    monkeypatch.setattr(scorer_mod, "score_postings", score_postings)
    return received
