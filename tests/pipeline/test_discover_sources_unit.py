"""`discover` with more than one source: a fake second source plugs in through the registry alone."""

import json
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

from door.commands import _common as common
from door.core import candidates, discovery_sources
from door.core import discovery_state as ds
from door.pipeline import discover
from door.scrapers.discovery import linkedin
import door.scrapers as scrapers
from profile_utils import write_config

VIEW = "https://www.linkedin.com/jobs/view/{}"


def li_employer(company, job_id="1"):
    return {"company": company, "titles": ["Data Scientist"], "job_ids": [job_id], "detailed": False,
            "first_seen": "2026-10-01T00:00:00+00:00", "links": [VIEW.format(job_id)]}


def result(employers, **kw):
    out = {"employers": employers, "details": 0, "pages": 1, "requests": 1, "stopped": None, "pushback": False,
           "outcome": "ok", "mode": "rotate", "mode_switched": False, "searched": [], "search_complete": True,
           "first_429": None, "budget": 150, "pause": [2.0, 4.0], "seconds": 1}
    out.update(kw)
    return out


@pytest.fixture
def two(env, monkeypatch):
    """LinkedIn and a fake Hungarian source, both faked; the profile is in Budapest."""
    st = types.SimpleNamespace(li=[], fake=[], li_raises=None, fake_raises=None, li_pushback=False,
                               fake_pushback=False, fake_calls=[])
    mod = types.ModuleType("fake_source")
    mod.NAME, mod.COUNTRIES, mod.CONFIG_KEY = "fake", ("hu",), "fake_discovery"

    def fake_run(config, **kw):
        st.fake_calls.append(kw)
        scrapers.record_error("fake", "fake problem")
        if st.fake_raises:
            raise st.fake_raises
        if st.fake_pushback:
            scrapers.record_pushback("fake")
            return result(st.fake, stopped="HTTP 429", pushback=True, outcome="refused")
        return result(st.fake, budget=kw["budget"])

    mod.run = fake_run
    monkeypatch.setitem(sys.modules, "fake_source", mod)
    monkeypatch.setitem(discovery_sources.SOURCES, "fake", "fake_source")

    def li_run(config, **kw):
        scrapers.record_error("linkedin", "li problem")
        if st.li_raises:
            raise st.li_raises
        if st.li_pushback:
            scrapers.record_pushback("linkedin")
            return result(st.li, stopped="HTTP 429", pushback=True, outcome="refused")
        return result(st.li, requests=2, pages=2)

    monkeypatch.setattr(linkedin, "discover_run", li_run)
    real = common._load_config
    extra = {"fake_discovery": True}  # a source runs only once the user turned it on
    st.extra = extra
    monkeypatch.setattr(common, "_load_config", lambda pd: {**real(pd), **extra})
    write_config(env.profile_dir, {"role_targets": ["data scientist"], "location": "Budapest", "linkedin_discovery": True})
    return st


def run(env):
    return discover._discover_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)


def test_the_fake_runs_for_a_hungarian_profile_and_is_skipped_for_a_danish_one(env, two):
    two.fake = [li_employer("Magyar", "9")]
    block = run(env)
    assert block["sources"]["fake"]["skipped"] is None and len(two.fake_calls) == 1
    write_config(env.profile_dir, {"role_targets": ["data scientist"], "location": "Copenhagen", "linkedin_discovery": True})
    block = run(env)
    assert block["sources"]["fake"]["skipped"] == "not for dk" and len(two.fake_calls) == 1
    assert block["sources"]["linkedin"]["skipped"] is None


def test_the_fake_queues_under_its_name_and_keeps_its_own_state(env, two):
    two.fake = [li_employer("Magyar", "9")]
    two.li = [li_employer("Pleo", "7")]
    block = run(env)
    queue = candidates.load(env.jobs_dir)
    assert queue["magyar"]["sources"] == ["fake"] and queue["pleo"]["sources"] == ["linkedin"]
    assert (env.jobs_dir / "discovery" / "fake.json").exists() and (env.jobs_dir / "discovery" / "linkedin.json").exists()
    assert ds.load(env.jobs_dir, "fake")["last_run"] and ds.load(env.jobs_dir, "linkedin")["last_run"]
    assert block["employers"] == 2 and block["queued"] == 2 and block["requests"] == 3
    assert block["sources"]["fake"]["queued"] == 1 and block["sources"]["linkedin"]["employers"] == 1


def test_one_source_resting_does_not_block_the_other(env, two):
    ds.save(env.jobs_dir, "linkedin", {"pushback_at": datetime.now(timezone.utc).isoformat(), "seen": {}})
    two.fake = [li_employer("Magyar", "9")]
    block = run(env)
    assert block["skipped"] is None
    assert block["sources"]["linkedin"]["skipped"].startswith("LinkedIn resting until ")
    assert set(candidates.load(env.jobs_dir)) == {"magyar"}


def test_a_key_off_skips_only_that_source(env, two):
    two.extra["fake_discovery"] = False
    two.li = [li_employer("Pleo", "7")]
    block = run(env)
    assert block["sources"]["fake"]["skipped"] == "fake_discovery is off" and two.fake_calls == []
    assert block["sources"]["linkedin"]["queued"] == 1


def test_a_crash_in_the_fake_is_reported_and_linkedin_still_queues(env, two):
    two.fake_raises = RuntimeError("boom")
    two.li = [li_employer("Pleo", "7")]
    block = run(env)
    assert "boom" in block["sources"]["fake"]["error"] and block["sources"]["linkedin"]["error"] is None
    assert set(candidates.load(env.jobs_dir)) == {"pleo"} and "boom" in block["error"]


def test_the_step_is_skipped_only_when_every_source_is(env, two):
    two.extra.update(fake_discovery=False, linkedin_discovery=False, profession_discovery=False)
    block = run(env)
    assert set(block["skipped"].split("; ")) == {"fake_discovery is off", "linkedin_discovery is off",
                                                 "profession_discovery is off"}
    assert two.fake_calls == []


def test_errors_and_pushback_are_drained_per_source(env, two):
    two.fake_pushback = True
    run(env)
    assert scrapers.drain_errors("fake") == {} and scrapers.drain_errors("linkedin") == {}  # finish drained both
    assert scrapers.drain_pushback("fake") is False and scrapers.drain_pushback("linkedin") is False
    assert ds.load(env.jobs_dir, "fake")["pushback_at"] and "pushback_at" not in ds.load(env.jobs_dir, "linkedin")


def test_one_li_end_ends_the_discover_line_whichever_source_reports(env, two, progress_events):
    run(env)
    assert [e.stage for e in progress_events].count("li_end") == 1


def test_discover_lists_the_sources_it_reads_and_reports_each(env, two, progress_events):
    two.li_raises = RuntimeError("boom")
    run(env)
    listed = [json.loads(e.detail) for e in progress_events if e.stage == "items" and e.site == "discover"]
    assert listed == [[["linkedin", "LinkedIn"], ["fake", "fake"]]]
    marks = [(e.detail, e.outcome) for e in progress_events if e.stage == "item" and e.site == "discover"]
    assert marks == [("linkedin", "start"), ("linkedin", "failed"), ("fake", "start"), ("fake", "done")]


def test_a_source_that_was_refused_is_marked_failed(env, two, progress_events):
    two.fake_pushback = True
    run(env)
    marks = [(e.detail, e.outcome) for e in progress_events if e.stage == "item" and e.site == "discover"]
    assert ("fake", "failed") in marks and ("linkedin", "done") in marks


def test_a_skipped_source_is_not_listed(env, two, progress_events):
    two.extra["fake_discovery"] = False
    run(env)
    listed = [json.loads(e.detail) for e in progress_events if e.stage == "items" and e.site == "discover"]
    assert listed == [[["linkedin", "LinkedIn"]]]
