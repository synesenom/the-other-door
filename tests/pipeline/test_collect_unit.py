"""Step 4, `collect`: the feeds of the followed employers, with "new = not seen before" freshness."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from door.core import companies, freshness
from door.pipeline import collect
from pipeline_utils import fake_scraper, posting
from profile_utils import write_config


def follow(env, name, platform, entry, status="followed"):
    items = companies.load(env.profile_dir)
    companies.record(items, name, feed=(platform, entry) if status == "followed" else None, status=status,
                     found_via="manual", reason=None if status == "followed" else "x")
    companies.save(env.profile_dir, items)


def run(env, **kw):
    return collect._collect_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir, **kw)


def lever_posting(n, company="Acme", **kw):
    return posting(n, company, source="lever", url=f"https://jobs.lever.co/acme/{n}", **kw)


def test_each_platform_with_a_followed_employer_is_read_with_its_ids(env, monkeypatch):
    follow(env, "Acme", "lever", "acme")
    follow(env, "Globex", "lever", "globex")
    follow(env, "Initech", "greenhouse", "initech")
    follow(env, "Gone", "ashby", "gone", status="unresolved")
    seen = {}
    fake_scraper(monkeypatch, "lever", lambda config, **kw: seen.setdefault("lever", config) and [lever_posting(1)])
    fake_scraper(monkeypatch, "greenhouse", lambda config, **kw: seen.setdefault("greenhouse", config) and [])
    fake_scraper(monkeypatch, "ashby", lambda config, **kw: pytest.fail("nobody follows anyone on ashby"))

    block = run(env)

    assert seen["lever"]["lever_companies"] == ["acme", "globex"] and seen["lever"]["_mode"] == "collect"
    assert seen["greenhouse"]["greenhouse_boards"] == ["initech"]
    assert [e["site"] for e in block["sites"]] == ["lever", "greenhouse"] or {e["site"] for e in block["sites"]} == {"lever", "greenhouse"}
    assert block["employers"] == 3 and block["postings"] == 1
    assert block["summary"] == "3 employers, 1 postings"


def test_a_platform_needs_no_listing_in_the_profile(env, monkeypatch):
    follow(env, "Acme", "lever", "acme")
    fake_scraper(monkeypatch, "lever", lambda config, **kw: [lever_posting(1)])
    assert "lever" not in json.dumps(json.loads((env.profile_dir / "config.json").read_text()))
    assert run(env)["postings"] == 1


def test_a_posting_is_new_when_unseen_whatever_its_age(env, monkeypatch):
    follow(env, "Acme", "lever", "acme")
    ancient = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    # a watermark that would have cut it off, and max_age_days 30
    freshness.record_scrape(env.jobs_dir, "lever", datetime.now(timezone.utc))
    fake_scraper(monkeypatch, "lever", lambda config, **kw: [lever_posting(1, posted_at=ancient)])

    first = run(env)
    assert first["postings"] == 1 and first["sites"][0]["stale"] == 0

    again = run(env)
    assert again["postings"] == 0 and again["sites"][0]["outcome"] == "ok"  # seen before: history, not date


def test_the_scraper_gets_no_cutoff(env, monkeypatch):
    follow(env, "Acme", "lever", "acme")
    seen = {}
    fake_scraper(monkeypatch, "lever", lambda config, **kw: seen.update(kw) or [])
    run(env)
    assert seen["since"] is None


def test_collecting_does_not_move_any_watermark(env, monkeypatch):
    follow(env, "Acme", "lever", "acme")
    fake_scraper(monkeypatch, "lever", lambda config, **kw: [lever_posting(1)])
    run(env)
    assert "lever" not in freshness.load_scrape_state(env.jobs_dir)


def test_company_collects_just_those_employers(env, monkeypatch):
    follow(env, "Acme", "lever", "acme")
    follow(env, "Globex", "lever", "globex")
    follow(env, "Initech", "greenhouse", "initech")
    seen = {}
    fake_scraper(monkeypatch, "lever", lambda config, **kw: seen.setdefault("lever", config) and [])
    fake_scraper(monkeypatch, "greenhouse", lambda config, **kw: pytest.fail("not asked for"))

    block = run(env, companies=["globex"])

    assert seen["lever"]["lever_companies"] == ["globex"] and block["employers"] == 1


def test_company_must_be_a_followed_employer(env):
    follow(env, "Gone", "lever", "gone", status="unresolved")
    with pytest.raises(ValueError, match="not a followed employer"):
        run(env, companies=["Nobody"])
    with pytest.raises(ValueError, match="not a followed employer"):
        run(env, companies=["Gone"])


def test_nothing_followed_is_a_quiet_empty_step(env, progress_events):
    block = run(env)
    assert block["employers"] == 0 and block["sites"] == [] and block["summary"] == "no followed employers"
    assert [(e.site, e.outcome) for e in progress_events if e.stage == "step"] == [("collect", "start"), ("collect", "done")]


def test_failures_count_the_employers_that_did_not_load(env, monkeypatch):
    from door.scrapers import record_error

    follow(env, "Acme", "lever", "acme")
    follow(env, "Globex", "lever", "globex")

    def scrape(config, **kw):
        record_error("lever", "globex: HTTP 500")
        return [lever_posting(1)]

    fake_scraper(monkeypatch, "lever", scrape)
    block = run(env)
    assert block["failed"] == 1 and block["summary"] == "2 employers, 1 postings, 1 failed"


def test_a_crashing_platform_is_an_error_outcome(env, monkeypatch):
    follow(env, "Acme", "lever", "acme")
    fake_scraper(monkeypatch, "lever", lambda config, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    block = run(env)
    assert block["sites"][0]["outcome"] == "error" and block["failed"] == 1


def test_workable_reads_only_its_followed_accounts_when_collecting(env, monkeypatch):
    follow(env, "Dreamdata", "workable", "dreamdata")
    seen = {}
    fake_scraper(monkeypatch, "workable", lambda config, **kw: seen.update(config) or [])
    run(env)
    assert seen["_mode"] == "collect" and seen["workable_companies"] == ["dreamdata"]


def test_the_step_total_is_the_number_of_employers(env, monkeypatch, progress_events):
    follow(env, "Acme", "lever", "acme")
    fake_scraper(monkeypatch, "lever", lambda config, **kw: [])
    run(env)
    start = next(e for e in progress_events if e.stage == "step" and e.outcome == "start")
    assert start.total == 1


# --- retiring the employers that yield nothing relevant ---------------------------------------------------

def follow_found(env, name, platform, entry, days_ago, found_via="jobindex"):
    items = companies.load(env.profile_dir)
    when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")
    companies.record(items, name, feed=(platform, entry), status="followed", found_via=found_via, now=when)
    companies.save(env.profile_dir, items)


def by_name(env):
    return {c.name: c for c in companies.load(env.profile_dir)}


def test_an_employer_with_no_relevant_job_for_ninety_days_is_retired_before_collecting(env, monkeypatch):
    follow_found(env, "Idle", "lever", "idle", 100)
    follow_found(env, "Young", "greenhouse", "young", 10)
    seen = {}
    fake_scraper(monkeypatch, "lever", lambda config, **kw: pytest.fail("a dormant employer is not read"))
    fake_scraper(monkeypatch, "greenhouse", lambda config, **kw: seen.setdefault("g", config) and [])

    block = run(env)

    assert by_name(env)["Idle"].status == "dormant" and by_name(env)["Young"].status == "followed"
    assert by_name(env)["Idle"].reason == "no relevant job in 90 days" and by_name(env)["Idle"].feed.id == "idle"
    assert block["retired"] == ["Idle"] and block["employers"] == 1
    assert block["summary"] == "1 employers, 0 postings, 1 retired"
    assert seen["g"]["greenhouse_boards"] == ["young"]


def test_retire_after_days_is_configurable_and_zero_means_never(env, monkeypatch):
    from profile_utils import write_config

    write_config(env.profile_dir, {"role_targets": ["data scientist"], "retire_after_days": 0})
    follow_found(env, "Idle", "lever", "idle", 1000)
    fake_scraper(monkeypatch, "lever", lambda config, **kw: [])
    assert run(env)["retired"] == [] and by_name(env)["Idle"].status == "followed"
    write_config(env.profile_dir, {"role_targets": ["data scientist"], "retire_after_days": 30})
    follow_found(env, "Mid", "lever", "mid", 40)
    assert run(env)["retired"] == ["Idle", "Mid"]


def test_an_employer_added_by_hand_is_never_retired(env, monkeypatch):
    follow_found(env, "Mine", "lever", "mine", 1000, found_via="manual")
    fake_scraper(monkeypatch, "lever", lambda config, **kw: [])
    assert run(env)["retired"] == [] and by_name(env)["Mine"].status == "followed"


def test_a_collected_posting_on_topic_keeps_its_employer_active(env, monkeypatch):
    follow_found(env, "Busy", "lever", "busy", 100)
    follow_found(env, "Idle", "greenhouse", "idle", 100)
    follow_found(env, "OffTopic", "ashby", "off", 100)
    # collect retires first, so a stamp from an earlier run is what keeps Busy
    items = companies.load(env.profile_dir)
    companies.mark_relevant(items, "Busy", (datetime.now(timezone.utc) - timedelta(days=5)).isoformat())
    companies.save(env.profile_dir, items)
    fake_scraper(monkeypatch, "lever", lambda config, **kw: [lever_posting(1, "Busy")])
    block = run(env)
    assert block["retired"] == ["Idle", "OffTopic"] and by_name(env)["Busy"].status == "followed"


def test_collected_postings_are_stamped_by_title_and_by_name(env, monkeypatch):
    follow_found(env, "Busy", "lever", "busy", 10)
    follow_found(env, "Quiet", "lever", "quiet", 10)
    fake_scraper(monkeypatch, "lever", lambda config, **kw: [
        lever_posting(1, "Busy"), lever_posting(2, "Quiet", title="Pedagogue", platform_id="p2")])

    run(env)

    assert by_name(env)["Busy"].last_relevant is not None and by_name(env)["Quiet"].last_relevant is None


def test_companies_naming_a_dormant_employer_is_refused(env):
    follow_found(env, "Idle", "lever", "idle", 100)
    items = companies.load(env.profile_dir)
    companies.retire_idle(items, 90)
    companies.save(env.profile_dir, items)
    with pytest.raises(ValueError, match="dormant"):
        run(env, companies=["Idle"])


# --- postings left unread because they are not local ---------------------------------------------------------

def test_non_local_postings_a_scraper_skipped_are_counted_per_site_and_in_the_summary(env, monkeypatch):
    from door.scrapers import record_non_local

    follow(env, "Acme", "lever", "acme")

    def scrape(config, **kw):
        record_non_local("lever", 1200)
        return [lever_posting(1)]

    fake_scraper(monkeypatch, "lever", scrape)

    block = run(env)

    assert block["sites"][0]["non_local"] == 1200 and block["non_local"] == 1200
    assert block["summary"] == "1 employers, 1 postings, 1,200 non-local skipped"
    fake_scraper(monkeypatch, "lever", lambda config, **kw: [])
    assert run(env)["non_local"] == 0  # drained: it does not leak into the next run


# --- postings whose title is off topic for the keywords ------------------------------------------------------

def test_an_off_topic_posting_is_not_written_but_counted_and_remembered(env, monkeypatch):
    from door.core.history import HistoryStore

    follow(env, "Acme", "lever", "acme")
    feed = [lever_posting(1), lever_posting(2, title="Machine Operator, night shift", platform_id="p2"),
            lever_posting(3, title="Pedagog til børnehave", platform_id="p3")]
    fake_scraper(monkeypatch, "lever", lambda config, **kw: feed)

    block = run(env)

    assert block["postings"] == 1 and [p.name for p in (env.jobs_dir / "postings" / block["run_date"] / "lever").iterdir()] == \
        ["lever-acme-1.json"]
    assert block["sites"][0]["off_topic"] == 2 and block["off_topic"] == 2
    assert block["summary"] == "1 employers, 1 postings, 2 off-topic skipped"
    assert not HistoryStore(env.jobs_dir / "history.json").is_new("lever-acme-3", "lever", None)  # seen: not checked again
    again = run(env)
    assert again["postings"] == 0 and again["off_topic"] == 0 and again["sites"][0]["outcome"] == "ok"


def test_keywords_without_a_content_word_make_nothing_off_topic(env, monkeypatch):
    write_config(env.profile_dir, {"role_targets": ["Senior"]})
    follow(env, "Acme", "lever", "acme")
    fake_scraper(monkeypatch, "lever", lambda config, **kw: [lever_posting(1, title="Pedagog", platform_id="p1")])
    block = run(env)
    assert block["postings"] == 1 and block["off_topic"] == 0


def test_search_keeps_off_topic_titles_the_board_returned(env, monkeypatch):
    from door.commands import scrape as scrape_cmd

    fake_scraper(monkeypatch, "jobindex", lambda config, **kw: [posting(1, title="Pedagog", platform_id="p1")])
    result = scrape_cmd._scrape_core(["jobindex"], jobs_dir=env.jobs_dir, profile_dir=env.profile_dir, passes=False)
    assert result["sites"][0]["count"] == 1 and "off_topic" not in result["sites"][0]


def test_a_late_collect_reports_late_events(env, monkeypatch, progress_events):
    follow(env, "Acme", "lever", "acme")
    fake_scraper(monkeypatch, "lever", lambda config, **kw: [lever_posting(1)])
    run(env, late=True)
    assert [(e.stage, e.outcome) for e in progress_events if e.outcome in ("start", "done") and e.site == "collect"] == [
        ("late", "start"), ("late", "done")]


def test_the_feed_scrapers_are_told_the_profile_country(env, monkeypatch):
    follow(env, "Dreamdata", "workable", "dreamdata")
    seen = {}
    fake_scraper(monkeypatch, "workable", lambda config, **kw: seen.update(config) or [])
    run(env)
    assert seen["_country"] == "dk"


def _named_lever(config, **kw):
    """A scraper that, like the real ones, labels a posting with the followed employer's name."""
    from door.scrapers import sdk

    return [lever_posting(n, sdk.followed_name(config, "lever_companies", entry, entry), platform_id=f"p{n}")
            for n, entry in enumerate(config["lever_companies"], 1)]


def test_a_collected_posting_carries_the_followed_employers_name_and_stamps_it(env, monkeypatch):
    follow_found(env, "Trustpilot", "lever", "trustpilot-feed", 10)
    fake_scraper(monkeypatch, "lever", _named_lever)

    run(env)

    written = [json.loads(p.read_text()) for p in (env.jobs_dir / "postings").rglob("*.json")]
    assert [w["company"] for w in written] == ["Trustpilot"]
    assert by_name(env)["Trustpilot"].last_relevant is not None


def test_a_company_collect_names_its_posting_the_same_way(env, monkeypatch):
    follow_found(env, "Trustpilot", "lever", "trustpilot-feed", 10)
    follow_found(env, "Globex", "lever", "globex-feed", 10)
    fake_scraper(monkeypatch, "lever", _named_lever)

    run(env, companies=["Globex"])

    written = [json.loads(p.read_text()) for p in (env.jobs_dir / "postings").rglob("*.json")]
    assert [w["company"] for w in written] == ["Globex"]


# --- a shared feed names its postings after the hiring agency (#308) ------------------------------------------

def _shared_posting(n, title="Data Scientist"):
    return posting(n, "Det Kongelige Bibliotek", source="hr_manager", title=title,
                   id=f"hr_manager.statensrekrutteringsloesning_tr-{n}", platform_id=f"statensrekrutteringsloesning_tr-{n}")


def test_a_posting_of_the_shared_feed_keeps_its_portal_active(env, monkeypatch):
    follow_found(env, "Statens Rekrutteringsløsning", "hr_manager", "statensrekrutteringsloesning_tr", 10)
    fake_scraper(monkeypatch, "hr_manager", lambda config, **kw: [_shared_posting(9)])

    run(env)

    assert by_name(env)["Statens Rekrutteringsløsning"].last_relevant is not None


def test_an_off_topic_posting_of_the_shared_feed_stamps_nothing(env, monkeypatch):
    follow_found(env, "Statens Rekrutteringsløsning", "hr_manager", "statensrekrutteringsloesning_tr", 10)
    fake_scraper(monkeypatch, "hr_manager", lambda config, **kw: [_shared_posting(9, title="Pedagogue")])

    run(env)

    assert by_name(env)["Statens Rekrutteringsløsning"].last_relevant is None


# --- the employer of a posting (#314) -------------------------------------------------------------------------

def _written(env):
    return {w["id"]: w for w in (json.loads(p.read_text()) for p in (env.jobs_dir / "postings").rglob("*.json"))}


def test_a_collected_posting_is_stamped_with_the_entry_it_belongs_to(env, monkeypatch):
    follow_found(env, "Novo Nordisk", "lever", "novo", 10)
    items = companies.load(env.profile_dir)
    items[0].aliases.append("Novo")
    companies.save(env.profile_dir, items)
    fake_scraper(monkeypatch, "lever", lambda config, **kw: [
        lever_posting(1, "Novo"), lever_posting(2, "Unrelated Ltd", platform_id="p2")])

    run(env)

    written = _written(env)
    assert written["lever-novo-1"]["employer"] == "Novo Nordisk"
    assert "employer" not in written["lever-unrelated-ltd-2"]


def test_a_shared_feed_posting_is_stamped_with_the_portal(env, monkeypatch):
    follow_found(env, "Statens Rekrutteringsløsning", "hr_manager", "statensrekrutteringsloesning_tr", 10)
    fake_scraper(monkeypatch, "hr_manager", lambda config, **kw: [_shared_posting(9)])

    run(env)

    assert [w["employer"] for w in _written(env).values()] == ["Statens Rekrutteringsløsning"]


# --------------------------------------------------------------------------- #
# an employer whose feed could not be read says so on the list (#437)
# --------------------------------------------------------------------------- #

def _problem(env, name):
    return companies.find(companies.load(env.profile_dir), name).collect_problem


def test_a_blocked_feed_is_stamped_on_its_employer_and_cleared_when_it_loads(env, monkeypatch):
    from door.scrapers import record_entry_error

    follow(env, "Acme", "lever", "acme")
    follow(env, "Globex", "lever", "globex")

    def blocked(config, **kw):
        record_entry_error("lever", "globex", "globex.example: bot protection; not attempted", blocked=True)
        return [lever_posting(1)]

    fake_scraper(monkeypatch, "lever", blocked)
    run(env)

    assert _problem(env, "Acme") is None
    globex = _problem(env, "Globex")
    assert globex.outcome == "blocked" and "bot protection" in globex.reason and globex.at

    fake_scraper(monkeypatch, "lever", lambda config, **kw: [lever_posting(2)])
    run(env)

    assert _problem(env, "Globex") is None


def test_a_scraper_that_raises_marks_every_employer_it_was_to_read(env, monkeypatch):
    follow(env, "Acme", "lever", "acme")

    def boom(config, **kw):
        raise RuntimeError("the site is down")

    fake_scraper(monkeypatch, "lever", boom)
    run(env)

    problem = _problem(env, "Acme")
    assert problem.outcome == "failed" and "the site is down" in problem.reason


def test_collecting_one_company_leaves_the_others_stamps(env, monkeypatch):
    from door.scrapers import record_entry_error

    follow(env, "Acme", "lever", "acme")
    follow(env, "Globex", "lever", "globex")

    def fail_globex(config, **kw):
        record_entry_error("lever", "globex", "error fetching 'globex': 500")
        return []

    fake_scraper(monkeypatch, "lever", fail_globex)
    run(env)
    fake_scraper(monkeypatch, "lever", lambda config, **kw: [lever_posting(3)])
    run(env, companies=["Acme"])

    assert _problem(env, "Globex") is not None
