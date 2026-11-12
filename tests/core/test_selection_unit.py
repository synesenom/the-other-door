"""Unit tests for selection.py (issue #67).

Pure offline tests for select_matches(): threshold filter, applied-exclusion,
sort order, and empty state. No network, no LLM — fixture JSONs on tmp_path.
"""

import json
from pathlib import Path

import pytest

from door.core.selection import (
    find_posting,
    find_posting_path,
    ledger_breakdown,
    pipeline_summary,
    select_matches,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_BASE = {
    "title": "Data Scientist",
    "company": "Acme",
    "location": "Copenhagen",
    "url": "https://example.com/job/1",
    "description": "d",
    "source": "jobindex",
    "scraped_at": "2026-06-14T00:00:00Z",
}


def _write_posting(jobs_dir: Path, date: str, site: str, job_id: str, **overrides) -> Path:
    site_dir = jobs_dir / "postings" / date / site
    site_dir.mkdir(parents=True, exist_ok=True)
    data = dict(_BASE, id=job_id, **overrides)
    path = site_dir / f"{job_id}.json"
    path.write_text(json.dumps(data))
    return path


class _FakeTracker:
    """Minimal stand-in for tracker.ApplicationTracker."""

    def __init__(self, statuses: dict):
        self._statuses = statuses

    def get_status(self, job_id):
        return self._statuses.get(job_id)


# --------------------------------------------------------------------------- #
# Empty state
# --------------------------------------------------------------------------- #

def test_select_matches_nonexistent_jobs_dir_returns_empty_list(tmp_path):
    jobs_dir = tmp_path / "does-not-exist"
    tracker = _FakeTracker({})

    result = select_matches(jobs_dir, tracker, min_score=0.6)

    assert result == []


# --------------------------------------------------------------------------- #
# Threshold filter
# --------------------------------------------------------------------------- #

def test_select_matches_drops_below_threshold(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-high", score=0.8)
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-low", score=0.3)
    tracker = _FakeTracker({})

    result = select_matches(jobs_dir, tracker, min_score=0.6)

    ids = [r["id"] for r in result]
    assert "job-high" in ids
    assert "job-low" not in ids


def test_select_matches_score_equal_to_threshold_is_kept(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-exact", score=0.6)
    tracker = _FakeTracker({})

    result = select_matches(jobs_dir, tracker, min_score=0.6)

    assert [r["id"] for r in result] == ["job-exact"]


def test_select_matches_none_score_excluded(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-unscored", score=None)
    tracker = _FakeTracker({})

    result = select_matches(jobs_dir, tracker, min_score=0.0)

    assert result == []


# --------------------------------------------------------------------------- #
# Applied-exclusion
# --------------------------------------------------------------------------- #

def test_select_matches_excludes_applied_jobs(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-applied", score=0.9)
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-new", score=0.9)
    tracker = _FakeTracker({"job-applied": "applied"})

    result = select_matches(jobs_dir, tracker, min_score=0.6)

    ids = [r["id"] for r in result]
    assert "job-applied" not in ids
    assert "job-new" in ids


def test_select_matches_untracked_and_new_status_are_eligible(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-untracked", score=0.9)
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-status-new", score=0.9)
    tracker = _FakeTracker({"job-status-new": "unapplied"})

    result = select_matches(jobs_dir, tracker, min_score=0.6)

    ids = [r["id"] for r in result]
    assert "job-untracked" in ids
    assert "job-status-new" in ids


# --------------------------------------------------------------------------- #
# Sort order
# --------------------------------------------------------------------------- #

def test_select_matches_sorted_by_score_descending(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-mid", score=0.7)
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-top", score=0.95)
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-bottom", score=0.61)
    tracker = _FakeTracker({})

    result = select_matches(jobs_dir, tracker, min_score=0.6)

    assert [r["id"] for r in result] == ["job-top", "job-mid", "job-bottom"]


# --------------------------------------------------------------------------- #
# Scores of zero and None
# --------------------------------------------------------------------------- #

def test_select_matches_excludes_none_score(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-unscored", score=None)

    assert select_matches(jobs_dir, _FakeTracker({}), min_score=0.0) == []


def test_select_matches_never_includes_a_zero_score(tmp_path):
    """A zero is a posting the prescreen or language pass dropped, never a match."""
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-zero", score=0.0)
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-low", score=0.05)
    tracker = _FakeTracker({})

    assert [r["id"] for r in select_matches(jobs_dir, tracker, min_score=0.0)] == ["job-low"]


# --------------------------------------------------------------------------- #
# Regression: malformed JSON, and jobs/output/ must not leak in
# --------------------------------------------------------------------------- #

def test_select_matches_skips_malformed_json(tmp_path):
    jobs_dir = tmp_path / "jobs"
    site_dir = jobs_dir / "postings" / "2026-07-01" / "jobindex"
    site_dir.mkdir(parents=True)
    (site_dir / "broken.json").write_text("{not valid json")
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-ok", score=0.9)
    tracker = _FakeTracker({})

    result = select_matches(jobs_dir, tracker, min_score=0.6)

    assert [r["id"] for r in result] == ["job-ok"]


def test_select_matches_ignores_output_directory(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-ok", score=0.9)
    # jobs/output/<job_id>/posting.json — generated application materials,
    # not a scraped posting. Must not be picked up by the walk.
    output_dir = jobs_dir / "output" / "job-ok"
    output_dir.mkdir(parents=True)
    (output_dir / "posting.json").write_text(json.dumps(
        dict(_BASE, id="job-ok", score=0.99)
    ))
    tracker = _FakeTracker({})

    result = select_matches(jobs_dir, tracker, min_score=0.6)

    assert len(result) == 1
    assert result[0]["id"] == "job-ok"


# --------------------------------------------------------------------------- #
# pipeline_summary (issue #71)
# --------------------------------------------------------------------------- #

def test_pipeline_summary_missing_jobs_dir_returns_all_zero(tmp_path):
    jobs_dir = tmp_path / "does-not-exist"
    tracker = _FakeTracker({})

    result = pipeline_summary(jobs_dir, tracker, min_score=0.6)

    assert result == {
        "total": 0, "excluded": 0, "applicable": 0, "above_threshold": 0, "unapplied": 0,
        "above_threshold_by_status": {"unapplied": 0, "prepared": 0, "applied": 0, "discarded": 0},
    }


def test_pipeline_summary_applicable_is_every_posting_scored_above_zero(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-dropped", score=0.0, score_reason="prescreen: 0.28 below cutoff")
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-excluded", score=0.0, score_reason="excluded")
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-unscored", score=None)
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-low", score=0.1)
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-high", score=0.9)

    assert pipeline_summary(jobs_dir, _FakeTracker({}), min_score=0.6)["applicable"] == 2


def test_pipeline_summary_splits_the_matches_by_ledger_status(tmp_path):
    jobs_dir = tmp_path / "jobs"
    for job_id in ("job-new", "job-untracked", "job-prepared", "job-applied", "job-interview", "job-ghosted", "job-offer", "job-gone"):
        _write_posting(jobs_dir, "2026-07-01", "jobindex", job_id, score=0.9)
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-low-applied", score=0.3)
    tracker = _FakeTracker({
        "job-new": "unapplied", "job-prepared": "prepared", "job-applied": "applied", "job-interview": "interview:technical",
        "job-ghosted": "ghosted", "job-offer": "offer", "job-gone": "discarded", "job-low-applied": "applied",
    })

    by_status = pipeline_summary(jobs_dir, tracker, min_score=0.6)["above_threshold_by_status"]

    # applied counts everything past applying (interview, ghosted, offer, rejected); below-threshold postings don't count.
    assert by_status == {"unapplied": 2, "prepared": 1, "applied": 4, "discarded": 1}


def test_pipeline_summary_counts_total_regardless_of_score(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-scored", score=0.9)
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-unscored", score=None)
    tracker = _FakeTracker({})

    result = pipeline_summary(jobs_dir, tracker, min_score=0.6)

    assert result["total"] == 2


def test_pipeline_summary_counts_excluded_by_score_reason(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-excluded", score=0.0, score_reason="excluded")
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-duplicate", score=0.0, score_reason="duplicate")
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-expired", score=0.0, score_reason="expired")
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-ok", score=0.9)
    tracker = _FakeTracker({})

    result = pipeline_summary(jobs_dir, tracker, min_score=0.6)

    # Only score_reason == "excluded" is counted — duplicate/expired are not.
    assert result["excluded"] == 1
    assert result["total"] == 4


def test_pipeline_summary_counts_above_threshold(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-high", score=0.9)
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-exact", score=0.6)
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-low", score=0.3)
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-unscored", score=None)
    tracker = _FakeTracker({})

    result = pipeline_summary(jobs_dir, tracker, min_score=0.6)

    assert result["above_threshold"] == 2


def test_pipeline_summary_above_threshold_independent_of_tracker_status(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-applied", score=0.9)
    tracker = _FakeTracker({"job-applied": "applied"})

    result = pipeline_summary(jobs_dir, tracker, min_score=0.6)

    assert result["above_threshold"] == 1


def test_pipeline_summary_unapplied_matches_select_matches(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-new", score=0.9)
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-applied", score=0.9)
    tracker = _FakeTracker({"job-applied": "applied"})

    result = pipeline_summary(jobs_dir, tracker, min_score=0.6)
    expected = len(select_matches(jobs_dir, tracker, min_score=0.6))

    assert result["unapplied"] == expected == 1


def test_pipeline_summary_skips_malformed_json(tmp_path):
    jobs_dir = tmp_path / "jobs"
    site_dir = jobs_dir / "postings" / "2026-07-01" / "jobindex"
    site_dir.mkdir(parents=True)
    (site_dir / "broken.json").write_text("{not valid json")
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-ok", score=0.9)
    tracker = _FakeTracker({})

    result = pipeline_summary(jobs_dir, tracker, min_score=0.6)

    assert result["total"] == 1


def test_pipeline_summary_ignores_output_directory(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-ok", score=0.9)
    output_dir = jobs_dir / "output" / "job-ok"
    output_dir.mkdir(parents=True)
    (output_dir / "posting.json").write_text(json.dumps(
        dict(_BASE, id="job-ok", score=0.99)
    ))
    tracker = _FakeTracker({})

    result = pipeline_summary(jobs_dir, tracker, min_score=0.6)

    assert result["total"] == 1


# --------------------------------------------------------------------------- #
# ledger_breakdown (issue #71)
# --------------------------------------------------------------------------- #

def test_ledger_breakdown_zero_fills_known_statuses_for_empty_ledger():
    result = ledger_breakdown({})

    from door.core.tracker import STATUSES

    assert result == dict.fromkeys(STATUSES, 0)


def test_ledger_breakdown_tallies_mixed_statuses():
    applications = {
        "job-a": {"status": "applied", "updated_at": "2026-07-01T00:00:00Z"},
        "job-b": {"status": "applied", "updated_at": "2026-07-02T00:00:00Z"},
        "job-c": {"status": "unapplied", "updated_at": "2026-07-03T00:00:00Z"},
        "job-d": {"status": "interview:technical", "updated_at": "2026-07-04T00:00:00Z"},
    }

    result = ledger_breakdown(applications)

    assert result["applied"] == 2
    assert result["unapplied"] == 1
    assert result["interview:technical"] == 1
    assert result["rejected"] == 0
    assert result["offer"] == 0
    assert result["discarded"] == 0
    assert result["prepared"] == 0


def test_ledger_breakdown_tallies_unknown_status_without_crashing():
    applications = {
        "job-a": {"status": "prepared", "updated_at": "2026-07-01T00:00:00Z"},
        "job-b": {"status": "some-future-status", "updated_at": "2026-07-02T00:00:00Z"},
    }

    result = ledger_breakdown(applications)

    assert result["prepared"] == 1
    assert result["some-future-status"] == 1


# --------------------------------------------------------------------------- #
# find_posting (issue #70)
# --------------------------------------------------------------------------- #

def test_find_posting_returns_matching_dict(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-a", title="Data Scientist")
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-b", title="ML Engineer")

    result = find_posting(jobs_dir, "job-b")

    assert result is not None
    assert result["id"] == "job-b"
    assert result["title"] == "ML Engineer"


def test_find_posting_returns_none_when_not_found(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-a")

    result = find_posting(jobs_dir, "does-not-exist")

    assert result is None


def test_find_posting_nonexistent_jobs_dir_returns_none(tmp_path):
    jobs_dir = tmp_path / "does-not-exist"

    result = find_posting(jobs_dir, "job-a")

    assert result is None


def test_find_posting_skips_malformed_json(tmp_path):
    jobs_dir = tmp_path / "jobs"
    site_dir = jobs_dir / "postings" / "2026-07-01" / "jobindex"
    site_dir.mkdir(parents=True)
    (site_dir / "broken.json").write_text("{not valid json")
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-ok")

    result = find_posting(jobs_dir, "job-ok")

    assert result is not None
    assert result["id"] == "job-ok"


def test_find_posting_ignores_output_directory(tmp_path):
    jobs_dir = tmp_path / "jobs"
    output_dir = jobs_dir / "output" / "job-in-output"
    output_dir.mkdir(parents=True)
    (output_dir / "posting.json").write_text(json.dumps(
        dict(_BASE, id="job-in-output")
    ))

    result = find_posting(jobs_dir, "job-in-output")

    assert result is None


def test_find_posting_tie_break_returns_first_in_sorted_walk_order(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-02", "jobindex", "dup-job", title="Later Copy")
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "dup-job", title="Earlier Copy")

    result = find_posting(jobs_dir, "dup-job")

    assert result["title"] == "Earlier Copy"


# --------------------------------------------------------------------------- #
# find_posting_path (issue #72)
# --------------------------------------------------------------------------- #

def test_find_posting_path_returns_matching_file_path(tmp_path):
    jobs_dir = tmp_path / "jobs"
    path = _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-a", title="Data Scientist")

    result = find_posting_path(jobs_dir, "job-a")

    assert result == path


def test_find_posting_path_returns_none_when_missing(tmp_path):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-a")

    result = find_posting_path(jobs_dir, "does-not-exist")

    assert result is None


# --------------------------------------------------------------------------- #
# Job references by name (issue #312)
# --------------------------------------------------------------------------- #

from door.core.selection import AmbiguousJobRef, resolve_job_ref  # noqa: E402


def _ledger(jobs_dir: Path, statuses: dict) -> None:
    (jobs_dir / "applications.json").write_text(json.dumps(
        {job_id: {"status": status, "updated_at": "2026-10-01T00:00:00+00:00", "history": []}
         for job_id, status in statuses.items()}))


def _three(jobs_dir: Path) -> None:
    _write_posting(jobs_dir, "2026-10-25", "greenhouse", "greenhouse.trustpilot.dsm", company="Trustpilot",
                   title="Data Science Manager", score=0.8)
    _write_posting(jobs_dir, "2026-10-25", "successfactors", "sf.flugger.ai", company="Flügger group A/S",
                   title="AI & MarTech Lead", score=0.5)
    _write_posting(jobs_dir, "2026-10-25", "jobindex", "jobindex.novo.ml", company="Novo Nordisk",
                   title="Senior Machine Learning Engineer", score=0.45, title_en="Senior Machine Learning Engineer")


def test_a_unique_company_word_names_the_job(tmp_path):
    _three(tmp_path)
    assert resolve_job_ref("trustpilot", tmp_path) == "greenhouse.trustpilot.dsm"
    assert resolve_job_ref("Novo machine", tmp_path) == "jobindex.novo.ml"  # words across company and title


def test_names_match_without_case_or_accents(tmp_path):
    _three(tmp_path)
    assert resolve_job_ref("FLUGGER", tmp_path) == "sf.flugger.ai"
    assert resolve_job_ref("flügger martech", tmp_path) == "sf.flugger.ai"


def test_a_word_matches_the_start_of_a_word_only(tmp_path):
    _three(tmp_path)
    with pytest.raises(ValueError, match="no job matches 'pilot manager'"):
        resolve_job_ref("pilot manager", tmp_path)
    assert resolve_job_ref("pilot", tmp_path) == "pilot"  # one word nothing matches: read as an id


def test_several_matches_raise_with_the_candidates_best_first(tmp_path):
    _three(tmp_path)
    _write_posting(tmp_path, "2026-10-25", "jobindex", "jobindex.trustpilot.ml", company="Trustpilot",
                   title="ML Engineer", score=0.9)
    with pytest.raises(AmbiguousJobRef) as exc:
        resolve_job_ref("trustpilot", tmp_path)
    assert [c["job_id"] for c in exc.value.candidates] == ["jobindex.trustpilot.ml", "greenhouse.trustpilot.dsm"]
    assert exc.value.candidates[0] == {"job_id": "jobindex.trustpilot.ml", "title": "ML Engineer",
                                       "company": "Trustpilot", "status": "unapplied"}
    assert isinstance(exc.value, ValueError) and "2 jobs match 'trustpilot'" in str(exc.value)


def test_a_job_in_play_wins_over_other_postings(tmp_path):
    _three(tmp_path)
    _write_posting(tmp_path, "2026-10-25", "jobindex", "jobindex.trustpilot.ml", company="Trustpilot",
                   title="ML Engineer", score=0.9)
    _ledger(tmp_path, {"greenhouse.trustpilot.dsm": "interview:screening"})
    assert resolve_job_ref("trustpilot", tmp_path) == "greenhouse.trustpilot.dsm"


def test_discarded_jobs_and_duplicates_are_not_matched_by_name(tmp_path):
    _three(tmp_path)
    _write_posting(tmp_path, "2026-10-25", "jobindex", "jobindex.trustpilot.dsm", company="Trustpilot",
                   title="Data Science Manager", score=0.8, duplicate_of="greenhouse.trustpilot.dsm")
    _write_posting(tmp_path, "2026-10-25", "manual", "manual.trustpilot.x", company="Trustpilot", title="X")
    _ledger(tmp_path, {"manual.trustpilot.x": "discarded"})
    assert resolve_job_ref("trustpilot", tmp_path) == "greenhouse.trustpilot.dsm"


def test_an_exact_job_id_is_itself(tmp_path):
    _three(tmp_path)
    _ledger(tmp_path, {"linkedin.gone.job": "applied"})  # in the ledger, no posting on disk
    assert resolve_job_ref("sf.flugger.ai", tmp_path) == "sf.flugger.ai"
    assert resolve_job_ref("linkedin.gone.job", tmp_path) == "linkedin.gone.job"
    assert resolve_job_ref("jobindex-unknown-id", tmp_path) == "jobindex-unknown-id"  # id-shaped, nothing matches


def test_digits_are_words_not_ranks(tmp_path):
    _three(tmp_path)
    (tmp_path / "last_list.json").write_text('{"ranks": {"3": "greenhouse.trustpilot.dsm"}}')
    assert resolve_job_ref("3", tmp_path) == "3"


def test_no_match_and_an_empty_reference_error_clearly(tmp_path):
    _three(tmp_path)
    with pytest.raises(ValueError, match="no job matches 'acme corp'"):
        resolve_job_ref("acme corp", tmp_path)
    with pytest.raises(ValueError, match="no job given"):
        resolve_job_ref("  ", tmp_path)


@pytest.mark.parametrize("ref", ["../etc"])
def test_resolve_job_ref_rejects_invalid_slugs(tmp_path, ref):
    with pytest.raises(ValueError):
        resolve_job_ref(ref, tmp_path)


def _count_walks(monkeypatch) -> list:
    from door.core import selection

    walks: list = []
    real = selection.iter_postings

    def counting(jobs_dir):
        walks.append(jobs_dir)
        return real(jobs_dir)

    monkeypatch.setattr(selection, "iter_postings", counting)
    return walks


def test_pipeline_summary_reads_the_postings_once(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    _write_posting(jobs_dir, "2026-07-01", "jobindex", "job-new", score=0.9)
    walks = _count_walks(monkeypatch)

    assert pipeline_summary(jobs_dir, _FakeTracker({}), min_score=0.6)["unapplied"] == 1
    assert len(walks) == 1


def test_pipeline_summary_and_select_matches_take_postings_already_read(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    postings = [dict(_BASE, id="job-new", score=0.9), dict(_BASE, id="job-low", score=0.1)]
    walks = _count_walks(monkeypatch)

    summary = pipeline_summary(jobs_dir, _FakeTracker({}), min_score=0.6, postings=postings)
    matches = select_matches(jobs_dir, _FakeTracker({}), min_score=0.6, postings=postings)

    assert (summary["total"], summary["unapplied"]) == (2, 1)
    assert [m["id"] for m in matches] == ["job-new"]
    assert walks == []
