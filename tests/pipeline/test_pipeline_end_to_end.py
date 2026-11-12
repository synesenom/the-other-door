"""All five real steps together, with only the outside faked: the boards, the employers' feeds, LinkedIn
and the scorer. A board shows an employer, `follow` finds its feed, `collect` reads it, `match` scores both."""

import json
from datetime import date

import pytest

from door.commands import find as find_cmd
from door.core import candidates, companies
from door.scrapers.discovery import linkedin
from pipeline_utils import fake_scraper, posting
from profile_utils import write_config


def test_a_board_posting_leads_to_a_followed_feed_that_is_collected_and_scored(env, monkeypatch, scorer, progress_events):
    write_config(env.profile_dir, {"role_targets": ["data scientist"], "location": "Copenhagen",
                                   "linkedin_discovery": True})
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: [
        posting(1, "Acme", apply_url="https://jobs.ashbyhq.com/acme/abc")])
    collected = {}
    fake_scraper(monkeypatch, "ashby", lambda config, **kw: collected.update(config) or [
        posting(2, "Acme", source="ashby", title="Senior Data Scientist", url="https://jobs.ashbyhq.com/acme/def", posted_at="2024-01-01T00:00:00+00:00")])
    monkeypatch.setattr(linkedin, "discover_run", lambda config, **kw: {
        "employers": [{"company": "Pleo", "titles": ["DS"], "job_ids": ["9"], "detailed": True, "first_seen": "2026-10-13T00:00:00+00:00",
                       "links": ["https://jobs.lever.co/pleo/1", "https://www.linkedin.com/jobs/view/9"]}],
        "details": 1, "pages": 1, "requests": 2, "stopped": None, "pushback": False, "outcome": "ok", "mode": "combined",
        "mode_switched": False, "searched": [], "search_complete": True, "first_429": None, "budget": kw["budget"],
        "pause": list(kw["pause"]), "seconds": 3})
    fake_scraper(monkeypatch, "lever", lambda config, **kw: [])

    record = find_cmd._find_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)

    assert record["steps"] == ["search", "discover", "follow", "collect", "match"] and record["failures"] == []
    followed = {c.name: (c.feed.platform, c.feed.id, c.found_via) for c in companies.load(env.profile_dir)}
    assert followed == {"Acme": ("ashby", "acme", "jobindex"), "Pleo": ("lever", "pleo", "linkedin")}
    assert candidates.load(env.jobs_dir) == {}
    assert collected["ashby_companies"] == ["acme"]
    assert record["collect"]["postings"] == 1 and record["collect"]["employers"] == 2
    # the collected posting is years old and still new to door: no date cutoff for an employer's feed
    day = env.jobs_dir / "postings" / date.today().isoformat()
    assert len(list(day.glob("jobindex/*.json"))) == 1 and len(list(day.glob("ashby/*.json"))) == 1
    scored = [json.loads(p.read_text())["score"] for p in day.glob("*/*.json")]
    assert scored == [0.9, 0.9] and record["match"]["scored"] == 2
    assert [e.site for e in progress_events if e.stage == "step" and e.outcome == "done"] == [
        "search", "discover", "follow", "collect", "match"]
    [log] = (env.jobs_dir / "runs" / "latest.log").read_text().splitlines()
    assert "discover: 1 employers, 1 queued, 1 pages + 1 job pages (2/150 requests, 2-4 s pause, combined)" in log
    # discover ran beside the others; if it ended after follow, Pleo was followed in the late pass
    assert "follow: 2 candidates: 2 followed" in log.replace(" + late: 1 candidates: 1 followed, 0 unfollowable, 0 unresolved", "") \
        or "follow: 1 candidates: 1 followed" in log
