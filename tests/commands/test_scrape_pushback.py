"""A site that pushed back rests before The other door asks it again.

- `door.core.freshness`: `record_pushback` stamps `pushback_at` in
  `jobs/scrape_state.json` (keeping the watermark), `resting_until` says until when
  a site with a `cooldown_hours` rests, and a clean scrape (`record_scrape`) clears it.
- `_scrape_core`: a scraper that calls `door.scrapers.record_pushback` gets the
  stamp; the next run within the cooldown skips the site without a request
  (outcome `resting`, a quiet skip). Scrapers are faked; offline.
"""

import types
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from door.commands import scrape as scrape_cmd
from door.core import freshness, sites, workspace
from door.scrapers import drain_pushback, record_error, record_pushback
from profile_utils import write_config

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def test_record_pushback_keeps_the_watermark_and_a_clean_scrape_clears_it(tmp_path):
    freshness.record_scrape(tmp_path, "linkedin", NOW - timedelta(days=2))
    freshness.record_pushback(tmp_path, "linkedin", NOW)
    assert freshness.load_scrape_state(tmp_path)["linkedin"] == {
        "last_success": (NOW - timedelta(days=2)).isoformat(), "pushback_at": NOW.isoformat(),
    }
    freshness.record_scrape(tmp_path, "linkedin", NOW + timedelta(days=1))
    assert freshness.load_scrape_state(tmp_path)["linkedin"] == {"last_success": (NOW + timedelta(days=1)).isoformat()}


def test_resting_until_is_the_pushback_plus_the_cooldown_while_it_lasts():
    state = {"linkedin": {"pushback_at": NOW.isoformat()}}
    assert freshness.resting_until("linkedin", 24, state, NOW + timedelta(hours=23)) == NOW + timedelta(hours=24)
    assert freshness.resting_until("linkedin", 24, state, NOW + timedelta(hours=24)) is None
    assert freshness.resting_until("linkedin", 0, state, NOW) is None  # a site without a cooldown never rests
    assert freshness.resting_until("jobindex", 24, state, NOW) is None


def test_the_pushback_channel_is_per_site_and_drains():
    record_pushback("linkedin")
    assert drain_pushback("profession") is False
    assert drain_pushback("linkedin") is True
    assert drain_pushback("linkedin") is False


def test_only_the_boards_that_push_back_rest_by_default():
    """The discovery sources rest through the `discover` engine after a refusal.
    Akademikernes Jobbank, behind Cloudflare, and the UK boards Reed and jobs.ac.uk rest a day after a refusal or a challenge; EURAXESS after a second 429."""
    assert {name: s.cooldown_hours for name, s in sites.SITES.items() if s.cooldown_hours} == {"jobbank": 24, "euraxess": 24, "reed": 24, "jobs_ac_uk": 24, "nhs_jobs": 24}


@pytest.fixture
def env(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    write_config(profile_dir, {"role_targets": ["data scientist"], "location": "Copenhagen"})
    jobs_dir = tmp_path / "jobs"
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)
    monkeypatch.setitem(sites.SITES, "jobindex", replace(sites.SITES["jobindex"], cooldown_hours=24))
    drain_pushback("jobindex")
    return types.SimpleNamespace(profile_dir=profile_dir, jobs_dir=jobs_dir)


@pytest.fixture
def fake_jobindex(monkeypatch):
    import door.scrapers.boards.jobindex as ji

    box = {"calls": 0, "push_back": False}

    def fake_scrape(config, **kwargs):
        box["calls"] += 1
        if box["push_back"]:
            record_error("jobindex", "stopped for this run: HTTP 429")
            record_pushback("jobindex")
        return []

    monkeypatch.setattr(ji, "scrape", fake_scrape)
    monkeypatch.delattr(ji, "iter_scrape", raising=False)
    return box


def _scrape(env):
    return scrape_cmd._scrape_core(["jobindex"], jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)


def test_a_site_that_pushed_back_rests_for_its_cooldown_without_a_request(env, fake_jobindex, capsys):
    fake_jobindex["push_back"] = True
    first = _scrape(env)
    assert first["sites"][0]["outcome"] == "failed"
    assert "pushback_at" in freshness.load_scrape_state(env.jobs_dir)["jobindex"]

    second = _scrape(env)
    entry = second["sites"][0]
    assert entry["site"] == "jobindex" and entry["outcome"] == "resting" and entry["until"]
    assert fake_jobindex["calls"] == 1  # no request while it rests
    scrape_cmd._echo_scrape_result(second)
    assert "resting after it pushed back" in capsys.readouterr().out


def test_after_the_cooldown_the_site_is_scraped_again(env, fake_jobindex):
    freshness.record_pushback(env.jobs_dir, "jobindex", datetime.now(timezone.utc) - timedelta(hours=25))
    assert _scrape(env)["sites"][0]["outcome"] != "resting"
    assert fake_jobindex["calls"] == 1


def test_a_failure_that_is_not_pushback_does_not_rest_the_site(env, fake_jobindex, monkeypatch):
    import door.scrapers.boards.jobindex as ji

    def failing(config, **kwargs):
        record_error("jobindex", "HTTP 503")
        return []

    monkeypatch.setattr(ji, "scrape", failing)
    _scrape(env)
    assert "pushback_at" not in freshness.load_scrape_state(env.jobs_dir).get("jobindex", {})
