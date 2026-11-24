"""`_match_core` scores at most `MAX_SCORED_PER_RUN` postings a run, chosen fairly across employers and sources (#551)."""

import json

import pytest

import door.matching.scorer as scorer_mod
from door.commands import match as match_cmd
from profile_utils import write_config


@pytest.fixture(autouse=True)
def _config(cli_env):
    write_config(cli_env.profile_dir, {"role_targets": ["data scientist"], "location": "Copenhagen", "max_age_days": None})


def _write(jobs_dir, site, job_id, **fields):
    folder = jobs_dir / "postings" / "2026-07-01" / site
    folder.mkdir(parents=True, exist_ok=True)
    data = {"id": job_id, "title": "Data Scientist", "company": "Acme", "location": "Copenhagen",
            "url": "https://example.com/1", "description": "d", "description_condensed": "d", "source": site,
            "scraped_at": "2026-06-14T00:00:00Z", "score": None, **fields}
    (folder / f"{job_id}.json").write_text(json.dumps(data))


def _stub_scorer(monkeypatch):
    seen: list[str] = []

    def fake(postings, *, on_result=None, model=None, **kw):
        results = {}
        for p in postings:
            seen.append(p["id"])
            results[p["id"]] = {"score": 0.9, "score_reason": "ok", "matching_skills": [], "missing_skills": [],
                                "scored_by": model, "scored_at": "2026-09-23T00:00:00+00:00"}
            if on_result:
                on_result(p["id"], results[p["id"]])
        return results, []

    monkeypatch.setattr(scorer_mod, "score_postings", fake)
    return seen


def test_a_flood_from_one_site_does_not_keep_another_sites_ads_from_being_scored(cli_env, monkeypatch):
    for i in range(1000):
        _write(cli_env.jobs_dir, "flood", f"flood.{i}", company=f"Fake{i % 3}", prescreen_score=0.99)
    for i in range(20):
        _write(cli_env.jobs_dir, "jobindex", f"jobindex.{i}", company=f"Real{i}", prescreen_score=0.3)
    seen = _stub_scorer(monkeypatch)

    result = match_cmd._match_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)

    assert len(seen) == match_cmd.MAX_SCORED_PER_RUN == 150
    assert -(-len(seen) // scorer_mod.DEFAULT_CHUNK) <= 30
    assert all(f"jobindex.{i}" in seen for i in range(20))
    assert result["scored"] == 150 and result["waiting"] == 870


def test_nothing_is_waiting_when_everything_fits_the_cap(cli_env, monkeypatch):
    _write(cli_env.jobs_dir, "jobindex", "jobindex.1")
    _stub_scorer(monkeypatch)
    assert match_cmd._match_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["waiting"] == 0
