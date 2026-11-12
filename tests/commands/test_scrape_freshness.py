"""`find`'s scrape stage keeps only postings published since that site's last scrape.

- `door.core.freshness`: `--days`, the per-site watermark in
  `jobs/scrape_state.json`, and the cutoff it implies (pure, no network).
- `_scrape_core`: drops postings published before the cutoff, reports how
  many, and advances a site's watermark only after a complete, successful
  scrape. Scrapers are faked; offline.
"""

import asyncio
import json
import types
from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner

from door.cli import cli
from door.commands import match as match_cmd
from door.commands import find as find_cmd
from door.commands import scrape as scrape_cmd
from door.core import workspace
import door.mcp_server as server
from door.core.freshness import (
    days_back,
    load_scrape_state,
    record_scrape,
    site_cutoff,
)
from profile_utils import write_config

NOW = datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# state + cutoff
# --------------------------------------------------------------------------- #

def test_record_and_load_scrape_state(tmp_path):
    assert load_scrape_state(tmp_path) == {}
    record_scrape(tmp_path, "jobindex", NOW)
    assert load_scrape_state(tmp_path) == {"jobindex": {"last_success": NOW.isoformat()}}


def test_cutoff_since_last_scrape_with_a_one_day_overlap():
    state = {"jobindex": {"last_success": NOW.isoformat()}}
    assert site_cutoff("jobindex", state, max_age_days=30, now=NOW) == NOW - timedelta(days=1)


def test_cutoff_first_scrape_falls_back_to_max_age_days():
    assert site_cutoff("thehub", {}, max_age_days=30, now=NOW) == NOW - timedelta(days=30)
    assert site_cutoff("thehub", {}, max_age_days=None, now=NOW) is None


def test_cutoff_is_capped_at_max_age_days_after_a_long_break():
    state = {"jobindex": {"last_success": (NOW - timedelta(days=60)).isoformat()}}
    assert site_cutoff("jobindex", state, max_age_days=30, now=NOW) == NOW - timedelta(days=30)
    assert site_cutoff("jobindex", state, max_age_days=None, now=NOW) == NOW - timedelta(days=61)


def test_days_back_rounds_up_to_whole_days():
    assert days_back(None, NOW) is None
    assert days_back(NOW - timedelta(days=14), NOW) == 14
    assert days_back(NOW - timedelta(days=1, hours=2), NOW) == 2
    assert days_back(NOW - timedelta(minutes=5), NOW) == 1
    assert days_back(NOW + timedelta(hours=1), NOW) == 1


# --------------------------------------------------------------------------- #
# _scrape_core
# --------------------------------------------------------------------------- #

@pytest.fixture
def env(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    write_config(profile_dir, {"role_targets": ["data scientist"], "location": "Copenhagen"})
    jobs_dir = tmp_path / "jobs"
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)
    return types.SimpleNamespace(profile_dir=profile_dir, jobs_dir=jobs_dir)


def _posting(pid: str, age_days: float | None) -> dict:
    now = datetime.now(timezone.utc)
    data = {
        "id": f"jobindex-acme-{pid}",
        "platform_id": pid,
        "title": "Data Scientist",
        "company": "Acme",
        "location": "Copenhagen",
        "url": f"https://x/{pid}",
        "description": "d",
        "source": "jobindex",
        "scraped_at": now.isoformat(),
    }
    if age_days is not None:
        data["posted_at"] = (now - timedelta(days=age_days)).isoformat()
    return data


@pytest.fixture
def fake_jobindex(monkeypatch):
    import door.scrapers.boards.jobindex as ji

    box = {"postings": [], "kwargs": None}

    def fake_scrape(config, **kwargs):
        box["kwargs"] = kwargs
        return list(box["postings"])

    monkeypatch.setattr(ji, "scrape", fake_scrape)
    monkeypatch.delattr(ji, "iter_scrape", raising=False)
    return box


def _site(result, name="jobindex"):
    return next(s for s in result["sites"] if s["site"] == name)


def _scrape(env, **kw):
    return scrape_cmd._scrape_core(["jobindex"], jobs_dir=env.jobs_dir, profile_dir=env.profile_dir, **kw)


def test_first_scrape_keeps_the_last_30_days_and_records_the_watermark(env, fake_jobindex):
    fake_jobindex["postings"] = [_posting("fresh", 3), _posting("old", 45), _posting("undated", None)]
    result = _scrape(env)
    site = _site(result)
    assert site["count"] == 2
    assert site["stale"] == 1
    assert site["since"] is not None
    written = {p.name for p in (env.jobs_dir / "postings").glob("*/jobindex/*.json")}
    assert written == {"jobindex-acme-fresh.json", "jobindex-acme-undated.json"}
    assert "jobindex" in load_scrape_state(env.jobs_dir)


def test_second_scrape_keeps_only_postings_since_the_last_one(env, fake_jobindex):
    last = datetime.now(timezone.utc) - timedelta(days=5)
    record_scrape(env.jobs_dir, "jobindex", last)
    fake_jobindex["postings"] = [_posting("today", 0), _posting("five-days", 5.5), _posting("ten-days", 10)]
    site = _site(_scrape(env))
    # cutoff = last scrape - 1 day overlap = 6 days ago
    assert site["count"] == 2
    assert site["stale"] == 1


def test_stale_postings_are_not_recorded_in_history(env, fake_jobindex):
    fake_jobindex["postings"] = [_posting("old", 45)]
    _scrape(env)
    history = json.loads((env.jobs_dir / "history.json").read_text()) if (env.jobs_dir / "history.json").exists() else {}
    assert "old" not in history


def test_cutoff_is_passed_to_the_scraper(env, fake_jobindex):
    _scrape(env)
    cutoff = fake_jobindex["kwargs"]["since"]
    assert abs((datetime.now(timezone.utc) - timedelta(days=30) - cutoff).total_seconds()) < 60


def test_watermark_not_advanced_when_the_site_fails(env, monkeypatch):
    import door.scrapers.boards.jobindex as ji

    def boom(config, **kwargs):
        raise RuntimeError("HTTP 500")

    monkeypatch.setattr(ji, "scrape", boom)
    monkeypatch.delattr(ji, "iter_scrape", raising=False)
    _scrape(env)
    assert load_scrape_state(env.jobs_dir) == {}


def test_watermark_not_advanced_when_the_per_site_cap_stopped_early(env, fake_jobindex):
    write_config(env.profile_dir, {
        "role_targets": ["data scientist"], "location": "Copenhagen",
        "max_postings_per_site": 2,
    })
    fake_jobindex["postings"] = [_posting("a", 0), _posting("b", 0), _posting("c", 0)]
    _scrape(env)
    assert load_scrape_state(env.jobs_dir) == {}


def test_watermark_not_advanced_when_the_site_returned_nothing(env, fake_jobindex):
    fake_jobindex["postings"] = []
    assert _site(_scrape(env))["outcome"] == "empty"
    assert load_scrape_state(env.jobs_dir) == {}


def test_only_stale_postings_is_ok_and_advances_the_watermark(env, fake_jobindex):
    fake_jobindex["postings"] = [_posting("old", 45)]
    assert _site(_scrape(env))["outcome"] == "ok"
    assert "jobindex" in load_scrape_state(env.jobs_dir)
