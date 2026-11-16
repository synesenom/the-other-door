"""The dicts the `_*_core` functions return, which the MCP tools hand over as-is (issue #144).

Offline — no network, no `claude`, no browser.
"""

import json
from datetime import datetime, timezone
import types
from pathlib import Path

import pytest

from door.commands import matches as matches_cmd
from door.commands import profile as profile_cmd
from door.commands import status as status_cmd
from door.core.profile_loader import ConfigError
from door.commands import prepare as prepare_cmd
from door.core import workspace
from profile_utils import write_config

# Within `list`'s default max_age_days (30) of today — a fixed June date would
# age out of the list as the calendar moves on (issue #146).
_FRESH_SCRAPED_AT = datetime.now(timezone.utc).isoformat()


@pytest.fixture
def env(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    jobs_dir = tmp_path / "jobs"
    write_config(profile_dir, {"min_score": 0.6})
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)
    return types.SimpleNamespace(profile_dir=profile_dir, jobs_dir=jobs_dir)


def _posting(jobs_dir: Path, job_id: str, *, date="2026-07-01", site="jobindex", **overrides) -> Path:
    site_dir = jobs_dir / "postings" / date / site
    site_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "id": job_id,
        "title": "Data Scientist",
        "company": "Acme",
        "location": "Copenhagen",
        "url": "https://example.com/job/1",
        "description": "A long description.",
        "source": site,
        "scraped_at": _FRESH_SCRAPED_AT,
    }
    data.update(overrides)
    path = site_dir / f"{job_id}.json"
    path.write_text(json.dumps(data))
    return path


def _ledger(jobs_dir: Path, entries: dict) -> None:
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / "applications.json").write_text(json.dumps({
        job_id: {"status": status, "updated_at": "2026-07-01T00:00:00Z"} for job_id, status in entries.items()
    }))


# --------------------------------------------------------------------------- #
# _list_core
# --------------------------------------------------------------------------- #

def test_list_core_returns_summaries_best_first_without_descriptions(env):
    _posting(env.jobs_dir, "job-mid", score=0.7)
    _posting(env.jobs_dir, "job-top", score=0.95, title="Lead DS")
    _posting(env.jobs_dir, "job-low", score=0.1)

    result = matches_cmd._list_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)

    assert result["min_score"] == 0.6
    assert [m["id"] for m in result["matches"]] == ["job-top", "job-mid"]
    top = result["matches"][0]
    assert top == {
        "id": "job-top", "score": 0.95, "title": "Lead DS", "title_en": None,
        "company": "Acme", "location": "Copenhagen", "work_permit": None, "status": "unapplied", "is_new": True,
        "updated_at": None, "rounds": [], "no_answer": False, "no_answer_days": 45,
    }
    assert all("description" not in m for m in result["matches"])


# --------------------------------------------------------------------------- #
# _status_summary_core
# --------------------------------------------------------------------------- #

def test_status_summary_core_returns_pipeline_and_ledger(env):
    _posting(env.jobs_dir, "job-excluded", score=0.0, score_reason="excluded")
    _posting(env.jobs_dir, "job-high", score=0.9)
    _posting(env.jobs_dir, "job-low", score=0.1)
    _ledger(env.jobs_dir, {"job-x": "applied", "job-y": "unapplied"})

    result = status_cmd._status_summary_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)

    assert result["min_score"] == 0.6
    assert result["pipeline"]["total"] == 3
    assert result["pipeline"]["above_threshold"] == 1
    ledger = result["ledger"]
    assert ledger["applied"] == 1
    assert ledger["unapplied"] == 1
    for label in ("prepared", "interview:screening", "rejected", "offer", "discarded"):
        assert ledger[label] == 0


# --------------------------------------------------------------------------- #
# _prepare_core
# --------------------------------------------------------------------------- #

def test_prepare_core_input_errors_raise(env):
    with pytest.raises(ValueError, match="invalid job_id"):
        prepare_cmd._prepare_core("../evil", jobs_dir=env.jobs_dir)
    with pytest.raises(LookupError, match="no posting found"):
        prepare_cmd._prepare_core("nope", jobs_dir=env.jobs_dir)


# --------------------------------------------------------------------------- #
# _init_core
# --------------------------------------------------------------------------- #

@pytest.fixture
def example_dir(tmp_path):
    import shutil

    example = tmp_path / "profile.example"
    shutil.copytree(workspace.PROFILE_EXAMPLE_DIR, example)
    config = json.loads((example / "config.json").read_text())
    for field, filename in (
        ("cv_content", "cv.md"),
    ):
        config[field] = str(example / filename)
    (example / "config.json").write_text(json.dumps(config))
    return example


def test_init_core_copies_merges_validates_and_writes(tmp_path, example_dir):
    profile_dir = tmp_path / "profile"

    result = profile_cmd._init_core(
        {"name": "Ada", "email": "ada@example.com", "role_targets": ["ML Lead"]},
        profile_dir=profile_dir, example_dir=example_dir,
    )

    assert result["config_path"] == str(profile_dir / "config.json")
    assert not any(name.endswith(".html") or name.startswith("fonts") for name in result["copied"])  # from the code (#56)
    assert "template" not in " ".join(json.loads((profile_dir / "config.json").read_text()))
    assert "cv.md" not in result["copied"]  # the example CV is never made the candidate's
    assert not (profile_dir / "cv.md").exists()
    written = json.loads((profile_dir / "config.json").read_text())
    assert written["name"] == "Ada"
    assert written["role_targets"] == ["ML Lead"]
    assert written["remote"] and "boards" not in written  # untouched fields come from the example


def test_init_core_saves_the_details_of_a_profile_with_no_cv(tmp_path, example_dir):
    profile_dir = tmp_path / "profile"
    profile_cmd._init_core({"name": "Ada", "email": "ada@example.com", "role_targets": ["ML Lead"]}, profile_dir=profile_dir, example_dir=example_dir)
    profile_cmd._init_core({"name": "Ada L."}, profile_dir=profile_dir, example_dir=example_dir)
    assert json.loads((profile_dir / "config.json").read_text())["name"] == "Ada L."
    assert not (profile_dir / "cv.md").exists()


def test_init_core_invalid_fields_raise_config_error_and_write_nothing(tmp_path, example_dir):
    profile_dir = tmp_path / "profile"
    with pytest.raises(ConfigError) as exc:
        profile_cmd._init_core({"role_targets": []}, profile_dir=profile_dir, example_dir=example_dir)
    assert any("role_targets" in line for line in exc.value.lines)
    assert not (profile_dir / "config.json").exists()


def _existing_config(profile_dir, example_dir, **extra):
    profile_dir.mkdir(parents=True, exist_ok=True)
    config = {**json.loads((example_dir / "config.json").read_text()), **extra}
    (profile_dir / "config.json").write_text(json.dumps(config))
    return config


def test_init_core_drops_the_keys_the_current_config_cannot_have(tmp_path, example_dir):
    """An unreadable config.json is no dead end: what in it is invalid and not set again is dropped, the rest kept."""
    profile_dir = tmp_path / "profile"
    before = _existing_config(profile_dir, example_dir, foo=1, min_score=5, max_age_days=14)

    result = profile_cmd._init_core({"name": "Ada"}, profile_dir=profile_dir, example_dir=example_dir)

    written = json.loads((profile_dir / "config.json").read_text())
    assert result["dropped"] == ["foo", "min_score"]
    assert "foo" not in written and "min_score" not in written
    assert written["name"] == "Ada"
    assert written["max_age_days"] == 14
    assert written["role_targets"] == before["role_targets"]


def test_init_core_validates_a_key_it_is_given_instead_of_dropping_it(tmp_path, example_dir):
    profile_dir = tmp_path / "profile"
    _existing_config(profile_dir, example_dir, min_score=5)
    with pytest.raises(ConfigError) as exc:
        profile_cmd._init_core({"min_score": 1.5}, profile_dir=profile_dir, example_dir=example_dir)
    assert any("min_score" in line for line in exc.value.lines)
    assert json.loads((profile_dir / "config.json").read_text())["min_score"] == 5


def test_init_core_drops_nothing_from_a_valid_config(tmp_path, example_dir):
    profile_dir = tmp_path / "profile"
    _existing_config(profile_dir, example_dir)
    assert profile_cmd._init_core({"name": "Ada"}, profile_dir=profile_dir, example_dir=example_dir)["dropped"] == []


def test_doctor_reports_missing_template_files(env):
    from door.core import doctor

    write_config(env.profile_dir, {"cv_template": str(env.profile_dir / "gone.html")})
    check = doctor.check_profile(env.profile_dir)
    assert check["status"] == "missing"
    assert "cv_template not found" in check["detail"]


def _failed_run(jobs_dir: Path, n: int, site: str = "thehub") -> None:
    runs = jobs_dir / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    at = f"2026-10-2{n}T09:00:00+00:00"
    record = {"started_at": at, "finished_at": at, "search": {"sites": [{"site": site, "outcome": "failed", "errors": ["HTTP 503"]}]}}
    (runs / f"2026-10-2{n}T09-00-00-00-00.json").write_text(json.dumps(record))


def test_status_summary_says_whether_something_keeps_going_wrong_and_no_more(env):
    """A board failing in each of its last three runs: `recurring_problem`, a yes or no, never the failures."""
    _failed_run(env.jobs_dir, 1)
    assert status_cmd._status_summary_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)["recurring_problem"] is False
    _failed_run(env.jobs_dir, 2)
    _failed_run(env.jobs_dir, 3)
    assert status_cmd._status_summary_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)["recurring_problem"] is True


def test_status_summary_reads_the_report_stamp_of_the_data_folder_holding_jobs(env):
    from door.core import recurring

    for n in (1, 2, 3):
        _failed_run(env.jobs_dir, n)
    recurring.stamp_report(env.jobs_dir.parent, datetime(2026, 10, 24, tzinfo=timezone.utc))
    assert status_cmd._status_summary_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)["recurring_problem"] is False


def test_status_summary_does_not_need_template_files(env):
    write_config(env.profile_dir, {"cv_template": str(env.profile_dir / "gone.html")})
    assert status_cmd._status_summary_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)["pipeline"]["total"] == 0


# --------------------------------------------------------------------------- #
# a full run reports its steps in order (issue #202)
# --------------------------------------------------------------------------- #

def _fixture_scraper(monkeypatch):
    import door.scrapers.boards.jobindex as ji
    from door.scrapers import record_error, report

    posting = {
        "id": "jobindex-acme-ds", "title": "Data Scientist", "company": "Acme", "location": "Copenhagen",
        "url": "https://x/1", "description": "We are looking for a data scientist to work with Python.",
        "source": "jobindex", "scraped_at": _FRESH_SCRAPED_AT,
    }

    def fake_scrape(config, **kwargs):
        report("'data scientist': 1 results")
        record_error("jobindex", "a recorded error")
        return [posting]

    monkeypatch.setattr(ji, "scrape", fake_scrape)
    monkeypatch.delattr(ji, "iter_scrape", raising=False)


def _fake_scorer(monkeypatch):
    import door.matching.scorer as scorer_mod

    def fake_score_postings(postings, *, on_result=None, model=None, **kw):
        for p in postings:
            on_result(p["id"], {"score": 0.9, "score_reason": "ok", "scored_by": model,
                                "scored_at": "2026-09-23T00:00:00+00:00"})
        return {}, []

    monkeypatch.setattr(scorer_mod, "score_postings", fake_score_postings)


def test_run_core_reports_each_step_in_order(env, monkeypatch, progress_events):
    from door.commands import companies as companies_cmd
    from door.commands import find as find_cmd

    _fixture_scraper(monkeypatch)
    _fake_scorer(monkeypatch)
    monkeypatch.setattr(companies_cmd, "_classify", lambda *a, **k: None)  # `follow` reads no pages
    find_cmd._find_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)
    steps = [(e.site, e.outcome) for e in progress_events if e.stage == "step"]
    assert [s for s in steps if s[1] != "skipped"] == [
        ("search", "start"), ("search", "done"), ("follow", "start"), ("follow", "done"),
        ("collect", "start"), ("collect", "done"), ("match", "start"), ("match", "done")]
    assert ("discover", "skipped") in steps  # linkedin_discovery is off in the test profile


# --------------------------------------------------------------------------- #
# interview stages
# --------------------------------------------------------------------------- #

def test_show_core_returns_the_whole_history_with_each_rounds_result(env):
    _posting(env.jobs_dir, "job-abc", score=0.8)
    status_cmd._set_status_core("job-abc", "applied", jobs_dir=env.jobs_dir)
    status_cmd._set_status_core("job-abc", "interview:screening", jobs_dir=env.jobs_dir)
    status_cmd._set_status_core("job-abc", "interview:assessment", jobs_dir=env.jobs_dir)

    result = matches_cmd._show_core("job-abc", jobs_dir=env.jobs_dir)

    assert [(e["status"], e.get("result")) for e in result["history"]] == [
        ("applied", None), ("interview:screening", "passed"), ("interview:assessment", "pending"),
    ]


def test_status_summary_core_tallies_the_interviews_by_stage(env):
    for job in ("job-a", "job-b"):
        _posting(env.jobs_dir, job, score=0.8)
        status_cmd._set_status_core(job, "interview:screening", jobs_dir=env.jobs_dir)
    status_cmd._set_status_core("job-a", "interview:technical", jobs_dir=env.jobs_dir)
    status_cmd._set_status_core("job-a", "rejected", jobs_dir=env.jobs_dir)

    result = status_cmd._status_summary_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)

    assert result["interviews"]["screening"] == {"passed": 1, "rejected": 0, "ghosted": 0, "withdrawn": 0, "pending": 1}
    assert result["interviews"]["technical"]["rejected"] == 1


def test_status_summary_core_gives_the_application_stage_and_each_stages_pass_rate(env):
    for job in ("job-a", "job-b", "job-c"):
        status_cmd._set_status_core(job, "applied", jobs_dir=env.jobs_dir)
    status_cmd._set_status_core("job-a", "interview:screening", jobs_dir=env.jobs_dir)
    status_cmd._set_status_core("job-b", "rejected", jobs_dir=env.jobs_dir)

    result = status_cmd._status_summary_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)

    assert result["application"] == {"passed": 1, "rejected": 1, "ghosted": 0, "withdrawn": 0, "pending": 1}
    assert list(result["pass_rates"]) == ["application", "screening"]
    assert (result["pass_rates"]["application"]["passed"], result["pass_rates"]["application"]["decided"]) == (1, 2)
    assert result["pass_rates"]["screening"]["rate"] is None


def _sent_with_scores(env, scores_and_steps):
    for n, (score, steps) in enumerate(scores_and_steps):
        job = f"job-{n}"
        _posting(env.jobs_dir, job, score=score)
        for step in steps:
            status_cmd._set_status_core(job, step, jobs_dir=env.jobs_dir)


def test_status_summary_core_compares_the_pass_rate_of_top_and_near_minimum_scores(env):
    _sent_with_scores(env, [(0.9, ["applied", "interview:screening"])] * 5 + [(0.5, ["applied", "rejected"])] * 5)

    result = status_cmd._status_summary_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)

    bands = result["pass_rates_by_score"]
    assert (bands["top"]["decided"], bands["near_min"]["decided"]) == (5, 5)
    assert bands["split"] == 0.9
    assert bands["reading"] == "near_min_lower"


def test_status_summary_core_has_no_score_bands_below_the_floor_or_without_postings(env):
    _sent_with_scores(env, [(0.9, ["applied", "interview:screening"])] * 2 + [(0.5, ["applied", "rejected"])] * 2)
    for n in range(10):  # sent, but no posting on disk
        status_cmd._set_status_core(f"ghost-{n}", "applied", jobs_dir=env.jobs_dir)
        status_cmd._set_status_core(f"ghost-{n}", "rejected", jobs_dir=env.jobs_dir)

    result = status_cmd._status_summary_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)

    assert result["pass_rates_by_score"] is None


def test_status_summary_core_keeps_the_first_positive_score_of_a_job_stored_twice(env):
    _sent_with_scores(env, [(0.9, ["applied", "interview:screening"])] * 5 + [(0.5, ["applied", "rejected"])] * 5)
    _posting(env.jobs_dir, "job-0", date="2026-08-01", score=None)  # a later, unscored copy of job-0

    result = status_cmd._status_summary_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)

    assert result["pass_rates_by_score"]["top"]["decided"] == 5
