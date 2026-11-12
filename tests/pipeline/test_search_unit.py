"""Step 1, `search`: the boards, and the employers they show queued for `follow`."""

import json

import pytest

from door.core import candidates, companies
from door.core import freshness
from door.core.progress import Progress
from door.pipeline import search
from pipeline_utils import fake_scraper, posting


def run(env, **kw):
    return search._search_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir, **kw)


def test_postings_are_written_as_ever_and_their_employers_queued(env, monkeypatch):
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: [
        posting(1, "Novo Nordisk A/S", apply_url="https://novonordisk.com/apply/1"), posting(2, "Novo Nordisk A/S"),
        posting(3, "Pleo"),
    ])

    block = run(env)

    assert block["step"] == "search" and block["boards"] == ["jobindex"] and block["postings"] == 3
    assert len(list((env.jobs_dir / "postings" / block["run_date"] / "jobindex").glob("*.json"))) == 3
    queue = candidates.load(env.jobs_dir)
    assert set(queue) == {"novonordisk", "pleo"}
    novo = queue["novonordisk"]
    assert novo["name"] == "Novo Nordisk A/S" and novo["sources"] == ["jobindex"]
    assert novo["links"] == ["https://novonordisk.com/apply/1", "https://www.jobindex.dk/jobannonce/1",
                             "https://www.jobindex.dk/jobannonce/2"]
    assert novo["titles"] == ["Data Scientist"] and novo["first_seen"] and novo["last_seen"]
    assert block["queued"] == 2


def test_an_employer_already_settled_is_not_queued(env, monkeypatch):
    items = []
    companies.record(items, "Pleo", feed=("ashby", "pleo"), status="followed", found_via="manual")
    companies.record(items, "Danske Bank", feed=None, status="unfollowable", found_via="jobindex", reason="Oracle")
    companies.save(env.profile_dir, items)
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: [posting(1, "Pleo"), posting(2, "Danske Bank"), posting(3, "Acme")])

    run(env)

    assert set(candidates.load(env.jobs_dir)) == {"acme"}


def test_the_queue_grows_across_runs_without_duplicates(env, monkeypatch):
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: [posting(1, "Acme")])
    run(env)
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: [posting(2, "Acme", platform_id="p2")])
    block = run(env)
    queue = candidates.load(env.jobs_dir)
    assert list(queue) == ["acme"] and len(queue["acme"]["links"]) == 2 and block["queued"] == 0


def test_boards_override_the_profile_and_must_be_boards(env, monkeypatch):
    seen = []
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: seen.append("jobindex") or [])
    fake_scraper(monkeypatch, "thehub", lambda config, **kw: seen.append("thehub") or [])
    block = run(env, boards=["thehub"])
    assert seen == ["thehub"] and block["boards"] == ["thehub"]
    with pytest.raises(ValueError, match="unknown board"):
        run(env, boards=["linkedin"])  # a discovery source (`discover`), not a board
    with pytest.raises(ValueError, match="unknown board"):
        run(env, boards=["greenhouse"])


def test_by_default_every_board_of_the_profile_country_is_searched(env, monkeypatch):
    from door.core import sites

    asked = []
    monkeypatch.setattr(sites, "boards_for_location", lambda location: asked.append(location) or ["jobindex", "thehub"])
    seen = []
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: seen.append("jobindex") or [])
    fake_scraper(monkeypatch, "thehub", lambda config, **kw: seen.append("thehub") or [])
    block = run(env)
    assert asked == ["Copenhagen"] and sorted(seen) == ["jobindex", "thehub"] and block["boards"] == ["jobindex", "thehub"]


def test_the_scrapers_are_told_they_are_searching(env, monkeypatch):
    seen = {}
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: seen.update(config) or [])
    run(env)
    assert seen["_mode"] == "search"


def test_boards_keep_the_watermark_rule(env, monkeypatch):
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    new = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    freshness.record_scrape(env.jobs_dir, "jobindex", datetime.now(timezone.utc) - timedelta(days=3))
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: [posting(1, "Old Co", posted_at=old), posting(2, "New Co", posted_at=new)])

    block = run(env)

    assert block["postings"] == 1 and set(candidates.load(env.jobs_dir)) == {"newco"}


def test_a_failed_board_is_counted_and_the_summary_says_so(env, monkeypatch):
    from door.scrapers import record_error

    def scrape(config, **kw):
        record_error("jobindex", "HTTP 500")
        return []

    fake_scraper(monkeypatch, "jobindex", scrape)
    block = run(env)
    assert block["failed"] == 1 and block["sites"][0]["outcome"] == "failed"
    assert block["summary"] == "0 postings from 1 boards, 1 failed"


def test_the_step_reports_itself_started_and_done(env, monkeypatch, progress_events):
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: [posting(1)])
    run(env)
    steps = [e for e in progress_events if e.stage == "step"]
    assert [(e.site, e.outcome) for e in steps] == [("search", "start"), ("search", "done")]
    listed = [e for e in progress_events if e.stage == "items"]
    assert [json.loads(e.detail) for e in listed] == [[["jobindex", "Jobindex"]]]  # its count: these boards
    assert steps[1].detail == "1 postings from 1 boards"


def test_the_passes_are_left_to_the_match_step(env, monkeypatch):
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: [posting(1)])
    block = run(env)
    data = json.loads(next((env.jobs_dir / "postings" / block["run_date"] / "jobindex").glob("*.json")).read_text())
    assert "prescreen_score" not in data and "description_condensed" not in data


def test_only_an_employer_with_a_fitting_title_is_queued(env, monkeypatch):
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: [
        posting(1, "Acme"), posting(2, "Acme", title="Pedagogue"),
        posting(3, "Kommune", title="Pedagogue"), posting(4, "Kommune", title="Social worker"),
    ])

    block = run(env)

    queue = candidates.load(env.jobs_dir)
    assert set(queue) == {"acme"} and block["queued"] == 1 and block["postings"] == 4
    assert queue["acme"]["titles"] == ["Data Scientist"]  # the unfitting ad is not what it was queued for


def test_search_keywords_decide_the_fit_before_role_targets(env, monkeypatch):
    from profile_utils import write_config

    write_config(env.profile_dir, {"role_targets": ["data scientist"],
                                   "search_keywords": ["pedagogue"], "location": "Copenhagen"})
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: [
        posting(1, "Acme"), posting(2, "Kommune", title="Pedagogue")])
    run(env)
    assert set(candidates.load(env.jobs_dir)) == {"kommune"}


@pytest.mark.parametrize("location, country", [("Copenhagen", "dk"), ("Denmark", "dk"), ("Remote", None), ("", None)])
def test_the_scrapers_are_told_the_profile_country(env, monkeypatch, location, country):
    from profile_utils import write_config

    write_config(env.profile_dir, {"role_targets": ["data scientist"], "location": location})
    seen = {}
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: seen.update(config) or [])
    run(env)
    assert seen["_country"] == country


# --- the employer of a posting (#314) -------------------------------------------------------------------------

def _written(env):
    return {p.name: json.loads(p.read_text()) for p in (env.jobs_dir / "postings").rglob("*.json")}


def test_a_posting_of_a_known_employer_or_alias_is_stamped_with_its_entry(env, monkeypatch):
    items = []
    companies.record(items, "Novo Nordisk", feed=("ashby", "novo"), status="followed", found_via="manual")
    items[0].aliases.append("Novo")
    companies.save(env.profile_dir, items)
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: [
        posting(1, "Novo"), posting(2, "Novo Nordisk A/S"), posting(3, "Pedagog", title="Pedagogue"),
        posting(4, "Novo", title="Pedagogue"), posting(5, "Stranger")])

    run(env)

    by_company = {}
    for p in _written(env).values():
        by_company.setdefault(p["company"], []).append(p.get("employer"))
    assert by_company["Novo"] == ["Novo Nordisk", "Novo Nordisk"]  # on topic or not
    assert by_company["Novo Nordisk A/S"] == ["Novo Nordisk"]
    assert by_company["Stranger"] == [None] and by_company["Pedagog"] == [None]


def test_stamp_employers_skips_unreadable_files(env, tmp_path):
    items = []
    companies.record(items, "Acme", feed=None, status="unresolved", found_via="manual", reason="x")
    companies.save(env.profile_dir, items)
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    good = tmp_path / "good.json"
    good.write_text(json.dumps(posting(1, "Acme")))
    search.stamp_employers([bad, tmp_path / "missing.json", good], env.profile_dir)
    assert json.loads(good.read_text())["employer"] == "Acme" and bad.read_text() == "{nope"


def test_search_lists_the_boards_it_reads_by_their_names(env, monkeypatch, progress_events):
    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: [posting(1, "Acme")])
    run(env)
    listed = [e for e in progress_events if e.stage == "items"]
    assert [(e.site, json.loads(e.detail)) for e in listed] == [("search", [["jobindex", "Jobindex"]])]
    stages = [(e.stage, e.outcome) for e in progress_events if e.stage in ("step", "items")]
    assert stages[:2] == [("step", "start"), ("items", None)]  # after the start, which clears the step


def test_a_resting_board_is_not_listed(env, monkeypatch, progress_events):
    from dataclasses import replace
    from datetime import datetime, timezone
    from door.core import sites
    monkeypatch.setitem(sites.SITES, "jobindex", replace(sites.SITES["jobindex"], cooldown_hours=24))
    freshness.record_pushback(env.jobs_dir, "jobindex", datetime.now(timezone.utc))
    run(env)
    assert [json.loads(e.detail) for e in progress_events if e.stage == "items"] == [[]]
