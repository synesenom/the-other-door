"""Unit tests for models.py (C1).

Covers make_job_id (<site>.<platform_id>), tenant_platform_id and the load_posting/save_posting round-trip.
Pure and offline — no network, no fixtures.
"""

from datetime import datetime, timezone

from door.core.models import JobPosting, load_posting, make_job_id, save_posting, tenant_platform_id


def _posting(**overrides) -> JobPosting:
    """A fully-populated JobPosting; override fields per test."""
    defaults = dict(
        id="thehub-acme-lead-data-scientist",
        title="Lead Data Scientist",
        company="Acme",
        location="Copenhagen, Denmark",
        url="https://thehub.io/jobs/acme/lead-data-scientist",
        description="Build models.",
        source="thehub",
        scraped_at=datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc),
        platform_id="abc123",
        posted_at=datetime(2026, 6, 1, 9, 30, tzinfo=timezone.utc),
        score=0.87,
        score_reason="strong title + skills match",
    )
    defaults.update(overrides)
    return JobPosting(**defaults)


# --------------------------------------------------------------------------- #
# make_job_id: <site>.<platform_id>
# --------------------------------------------------------------------------- #

def test_make_job_id_is_site_dot_platform_id():
    assert make_job_id("jobindex", "h1708816") == "jobindex.h1708816"
    assert make_job_id("workable", "b5ae9abb-1234-4cde-8f00-aa11bb22cc33") == "workable.b5ae9abb-1234-4cde-8f00-aa11bb22cc33"
    assert make_job_id("hr_manager", "kkdk-216610") == "hr_manager.kkdk-216610"


def test_make_job_id_normalises_odd_characters():
    assert make_job_id("x", "AbC/1 2") == "x.abc-1-2"
    assert make_job_id("x", "--A--") == "x.a"


def test_make_job_id_is_deterministic_and_distinct_per_platform_id():
    # Two jobs with the same company and title differ by platform id.
    assert make_job_id("jobindex", "h1") == make_job_id("jobindex", "h1")
    assert make_job_id("jobindex", "h1") != make_job_id("jobindex", "h2")


def test_make_job_id_is_a_valid_job_id():
    from door.core.utils import _validate_job_id

    _validate_job_id(make_job_id("jobindex", "H1/ 7"))


def test_tenant_platform_id_folds_the_host():
    assert tenant_platform_id("https://careers.x.com/job/1", "1431769533") == "careers.x.com-1431769533"


def test_tenant_platform_id_is_idempotent_and_tolerates_no_host():
    assert tenant_platform_id("https://careers.x.com/job/1", "careers.x.com-1") == "careers.x.com-1"
    assert tenant_platform_id("", "77") == "77"


# --------------------------------------------------------------------------- #
# save_posting / load_posting round-trip
# --------------------------------------------------------------------------- #

def test_save_load_round_trip_creates_parent_dirs(tmp_path):
    posting = _posting(
        liveness_status="live",
        duplicate_of="jobindex-acme-lead-data-scientist",
        matching_skills=["Python", "SQL"],
        missing_skills=["Kubernetes"],
        apply_type="external",
        apply_url="https://example.com/apply",
        description_condensed="Condensed text.",
        prescreen_score=0.42,
        scored_by="haiku",
        scored_at="2026-09-23T00:00:00+00:00",
    )
    path = tmp_path / "nested" / "deeper" / "posting.json"

    save_posting(posting, path)  # parents do not exist yet

    assert load_posting(path) == posting


def test_load_posting_legacy_json_without_newer_fields(tmp_path):
    """Old on-disk JSON lacking the fields added since (issues #44, #91, #93, #128, #143) still loads."""
    path = tmp_path / "legacy.json"
    path.write_text(
        """
        {
            "id": "thehub-acme-lead-data-scientist",
            "title": "Lead Data Scientist",
            "company": "Acme",
            "location": "Copenhagen, Denmark",
            "url": "https://thehub.io/jobs/acme/lead-data-scientist",
            "description": "Build models.",
            "source": "thehub",
            "scraped_at": "2026-06-13T12:00:00Z"
        }
        """
    )
    loaded = load_posting(path)
    assert loaded.liveness_status is None
    assert loaded.duplicate_of is None
    assert loaded.matching_skills == [] and loaded.missing_skills == []
    assert loaded.apply_type is None and loaded.apply_url is None
    assert loaded.description_condensed is None and loaded.prescreen_score is None
    assert loaded.scored_by is None and loaded.scored_at is None


def test_employer_round_trips_and_defaults_to_none(tmp_path):
    assert _posting().employer is None
    assert _posting(employer="Novo Nordisk").model_dump(mode="json")["employer"] == "Novo Nordisk"
    old = _posting().model_dump(mode="json")
    old.pop("employer")
    assert JobPosting.model_validate(old).employer is None


def test_integrity_is_kept_optional_and_old_json_validates():
    from door.core.models import JobPosting

    base = dict(id="x.1", title="t", company="c", location="l", url="u", description="d", source="x",
                scraped_at="2026-01-01T00:00:00Z")
    assert JobPosting.model_validate(base).integrity is None
    kept = JobPosting.model_validate({**base, "integrity": {"verdict": "clean", "findings": []}})
    assert kept.model_dump(mode="json")["integrity"] == {"verdict": "clean", "findings": []}
