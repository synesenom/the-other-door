"""All five real steps together, with only the outside faked: the boards, the employers' feeds, LinkedIn
and the scorer. A board shows an employer, `follow` finds its feed, `collect` reads it, `match` scores both."""

import json
import time
from datetime import date

import pytest

from door.commands import find as find_cmd
from door.core.jobs import candidates
from door.core.employers import companies
from door.scrapers.discovery import linkedin
from pipeline_utils import fake_scraper, posting
from profile_utils import write_config


@pytest.mark.parametrize("discover_late", [False, True], ids=["discover_on_time", "discover_after_follow"])
def test_a_board_posting_leads_to_a_followed_feed_that_is_collected_and_scored(env, monkeypatch, scorer, progress_events, discover_late):
    write_config(env.profile_dir, {"role_targets": ["data scientist"], "location": "Copenhagen",
                                   "linkedin_discovery": True})
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: [
        posting(1, "Acme", apply_url="https://jobs.ashbyhq.com/acme/abc")])
    collected = {}
    fake_scraper(monkeypatch, "ashby", lambda config, **kw: collected.update(config) or [
        posting(2, "Acme", source="ashby", title="Senior Data Scientist", url="https://jobs.ashbyhq.com/acme/def", posted_at="2024-01-01T00:00:00+00:00")])
    def discover_run(config, **kw):
        # discover runs on its own thread beside the other steps; held back, it ends after follow, as it may in a real run
        deadline = time.monotonic() + 10
        while discover_late and time.monotonic() < deadline and not any(
                e.stage == "step" and e.site == "follow" and e.outcome == "done" for e in list(progress_events)):
            time.sleep(0.01)
        return {
            "employers": [{"company": "Pleo", "titles": ["DS"], "job_ids": ["9"], "detailed": True, "first_seen": "2026-10-13T00:00:00+00:00",
                           "links": ["https://jobs.lever.co/pleo/1", "https://www.linkedin.com/jobs/view/9"]}],
            "details": 1, "pages": 1, "requests": 2, "stopped": None, "pushback": False, "outcome": "ok", "mode": "combined",
            "mode_switched": False, "searched": [], "search_complete": True, "first_429": None, "budget": kw["budget"],
            "pause": list(kw["pause"]), "seconds": 3}

    monkeypatch.setattr(linkedin, "discover_run", discover_run)
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
    done = [e.site for e in progress_events if e.stage == "step" and e.outcome == "done"]
    # every step reports its end; discover's thread ends whenever its reading does, the others in their order
    assert sorted(done) == sorted(["search", "discover", "follow", "collect", "match"])
    assert [name for name in done if name != "discover"] == ["search", "follow", "collect", "match"]
    [log] = (env.jobs_dir / "runs" / "latest.log").read_text().splitlines()
    assert "discover: 1 employers, 1 queued, 1 pages + 1 job pages (2/150 requests, 2-4 s pause, combined)" in log
    # discover ran beside the others; if it ended after follow, Pleo was followed in the late pass
    assert "follow: 2 candidates: 2 followed" in log.replace(" + late: 1 candidates: 1 followed, 0 unfollowable, 0 unresolved", "") \
        or "follow: 1 candidates: 1 followed" in log
