"""The saved sample of the newest release sets every field of every model the inventory names (#57).

`tests/data_versions/<X.Y.Z>/` is what the release gate opens. A sample that leaves a field unset could not catch a
step that drops it, so a field of `Profile`, a company entry, a posting, a ledger entry, and every status, must be
set somewhere in the newest sample. A new field is not in a sample written before it existed: it is listed in
`NEW_SINCE_RELEASE` below, which `/dev-release` empties when it saves the new release's sample (the field is then in
it, as `scripts/release_data_generate.py` sets it). A listed field that the sample does set fails too, so the list
never keeps a stale name.
"""

import json
import typing
from pathlib import Path

import pydantic
import pytest

from door.core import companies, models, profile_loader, stored, tracker
from release_gate_utils import releases

# Fields and files that exist in the current code but not in the newest saved release, as `<Model>.<field>` or the
# inventory pattern. Emptied when a release is saved (docs/releasing.md).
NEW_SINCE_RELEASE: set[str] = {"Profile.preferences"}

# Files the inventory names that a release's own sample does not hold, and why (never for lack of effort).
ABSENT_BY_DESIGN = {
    "profile/.data_version": "v0.1.0 wrote no version file; a later release's sample has it, this one does not need to",
    "jobs/.data_version": "same",
    "jobs/linkedin_discovery.json": "the state a version older than v0.1.0 kept; v0.1.0 writes jobs/discovery/linkedin.json",
    "upskill/**": "not in profile/ or jobs/, the two folders a sample holds",
}
# Inventory kinds that are the user's own data: a sample holds a file for each pattern of them.
_KINDS = (stored.CONFIG, stored.DATA, stored.LEDGER, stored.RECORD, stored.GENERATED)

NEWEST = releases()[-1] if releases() else None
pytestmark = pytest.mark.skipif(NEWEST is None, reason="no saved release")


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rows_of(model: type[pydantic.BaseModel], rows: list[dict], prefix: str, missing: set[str]) -> None:
    """Add to *missing* every field of *model* (and of the models inside it) that no row sets to something other than
    its default (a list or object: non-empty)."""
    for name, field in model.model_fields.items():
        default = field.get_default(call_default_factory=True)
        values = [row[name] for row in rows if isinstance(row, dict) and row.get(name) is not None]
        if isinstance(default, pydantic.BaseModel):
            default = default.model_dump()
        values = [v for v in values if v != default and v not in ([], {}, "")]
        if not values:
            missing.add(f"{prefix}.{name}")
            continue
        inner = next((a for a in typing.get_args(field.annotation) if isinstance(a, type) and issubclass(a, pydantic.BaseModel)), None)
        inner = inner or (field.annotation if isinstance(field.annotation, type) and issubclass(field.annotation, pydantic.BaseModel) else None)
        if inner is not None:
            _rows_of(inner, [v for v in values if isinstance(v, dict)], f"{prefix}.{name}", missing)


def _postings(sample: Path) -> list[dict]:
    return [_json(p) for p in sorted((sample / "jobs" / "postings").glob("*/*/*.json"))]


def _unset() -> set[str]:
    config = _json(NEWEST / "profile" / "config.json")
    missing: set[str] = set()
    _rows_of(profile_loader.Profile, [config], "Profile", missing)
    entries = _json(NEWEST / "profile" / "companies.json")["companies"]
    _rows_of(companies.Company, entries, "Company", missing)
    _rows_of(models.JobPosting, _postings(NEWEST), "JobPosting", missing)
    return missing


def test_every_model_field_is_set_in_the_sample_or_new_since_the_release():
    unset = _unset()
    assert not (unset - NEW_SINCE_RELEASE), (
        "set these in scripts/release_data_generate.py and save the sample again, or, when the field is newer than the "
        f"newest release, list it in NEW_SINCE_RELEASE: {sorted(unset - NEW_SINCE_RELEASE)}"
    )


def test_new_since_release_lists_only_what_the_sample_lacks():
    model_names = {f"Profile.{n}" for n in profile_loader.Profile.model_fields} | {f"Company.{n}" for n in companies.Company.model_fields} | {f"JobPosting.{n}" for n in models.JobPosting.model_fields}
    stale = {name for name in NEW_SINCE_RELEASE if name in model_names and name not in _unset()}
    unknown = {name for name in NEW_SINCE_RELEASE if "/" not in name and name not in model_names and "." not in name}
    assert not stale, f"the sample sets these now: remove them from NEW_SINCE_RELEASE: {sorted(stale)}"
    assert not unknown


def test_every_company_status_and_refusal_appears():
    entries = _json(NEWEST / "profile" / "companies.json")["companies"]
    assert {e["status"] for e in entries} == set(companies.STATUSES)
    assert {e["refusal"] for e in entries if e.get("refusal")} == {"must_not", "cant_yet"}
    assert {e["collect_problem"]["outcome"] for e in entries if e.get("collect_problem")} == {"blocked", "failed"}


def test_every_application_status_appears_and_the_ledger_entry_is_whole():
    ledger = _json(NEWEST / "jobs" / "applications.json")
    seen = {event["status"] for entry in ledger.values() for event in entry["history"]}
    assert seen == set(tracker.STATUSES), f"missing: {sorted(set(tracker.STATUSES) - seen)}"
    assert {entry["status"] for entry in ledger.values()} >= {"unapplied", "prepared", "applied", "offer", "rejected", "ghosted", "discarded"}
    entry_keys = {key for entry in ledger.values() for key in entry}
    event_keys = {key for entry in ledger.values() for event in entry["history"] for key in event}
    assert entry_keys == {"status", "updated_at", "notes", "materials", "history"}
    assert event_keys == {"status", "at", "notes", "logged_at"}


def test_every_data_file_the_inventory_names_is_in_the_sample():
    files = {p.relative_to(NEWEST).as_posix() for p in NEWEST.rglob("*") if p.is_file()}
    lacking = []
    for entry in stored.INVENTORY:
        if entry.kind not in _KINDS or entry.pattern in ABSENT_BY_DESIGN or entry.pattern in NEW_SINCE_RELEASE:
            continue
        rx = stored._regex(entry.pattern)
        if not any(rx.fullmatch(f) for f in files):
            lacking.append(entry.pattern)
    assert not lacking, f"the sample holds no file for: {lacking}"


def test_the_sample_holds_nothing_the_inventory_does_not_name():
    sample_files = [p.relative_to(NEWEST).as_posix() for p in NEWEST.rglob("*") if p.is_file() and p.name != "expected.json"]
    assert [f for f in sample_files if stored.named(f) is None] == []
