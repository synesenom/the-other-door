"""The release gate (#57): every earlier release's saved data opens in this build and reads back as it did.

Run by `./scripts/run-test.sh --release` (marker `release`), not by the offline suite or CI: between releases `main`
may not read the last release's data until `/dev-release` has written the upgrade step (#56).
"""

import json

import pytest

from door import version
from door.core import migrations
from door.core.migrations import Step
from release_gate_utils import check, check_refused, is_older_major, open_release, release_data, releases, sample_major

pytestmark = pytest.mark.release

SAMPLES = releases()


def test_there_is_a_saved_release():
    """Of any major: a release that bumps the major keeps the older samples until after its tag (dev-release 6b)."""
    assert SAMPLES, "tests/data_versions/ holds no release: scripts/save_release_data.py X.Y.Z saves one"


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: p.name)
def test_a_saved_release_upgrades_and_reads_back_equal(sample, tmp_path, monkeypatch):
    found = check(sample, tmp_path / "home", monkeypatch)
    assert not found, f"{sample.name}'s data reads back differently:\n" + "\n".join(found)


def _newest():
    """The newest sample of the current major (the older ones are only refused); the test skips without one."""
    current = [s for s in SAMPLES if not is_older_major(s)]
    if not current:
        pytest.skip("no saved release of this major yet: the older ones are refused, not upgraded")
    return current[-1]


def test_data_of_an_older_major_is_refused_and_untouched(tmp_path, monkeypatch):
    """Runs whatever majors are saved: the app is taken to be one major ahead of the newest sample, as it is between
    a major bump and the deletion of the older samples after the tag."""
    sample = SAMPLES[-1]
    monkeypatch.setattr(version, "VERSION", f"{sample_major(sample) + 1}.0.0")
    monkeypatch.setattr(migrations, "PROFILE_STEPS", [])
    monkeypatch.setattr(migrations, "JOBS_STEPS", [])
    found = check_refused(sample, tmp_path / "home", monkeypatch)
    assert not found, "\n".join(found)


def test_the_gate_expects_the_refusal_for_a_sample_of_an_older_major(tmp_path, monkeypatch):
    sample = SAMPLES[-1]
    monkeypatch.setattr(version, "VERSION", f"{sample_major(sample) + 1}.0.0")
    monkeypatch.setattr(migrations, "PROFILE_STEPS", [])
    monkeypatch.setattr(migrations, "JOBS_STEPS", [])
    assert is_older_major(sample)
    assert check(sample, tmp_path / "home", monkeypatch) == []  # old_major, data untouched: nothing to report


def test_a_change_no_step_lists_fails_the_gate(tmp_path, monkeypatch):
    """The steps run, but none of them says what it changes on purpose: the gate reports it."""
    unlisted = [Step(step.name, step.run) for step in migrations.PROFILE_STEPS]
    sample = _newest()
    status, now, changes = open_release(sample, tmp_path / "home", monkeypatch, profile_steps=unlisted)
    assert status is None and changes == []
    expected = json.loads((sample / "expected.json").read_text(encoding="utf-8"))
    if not release_data.differences(expected, now):
        pytest.skip("the current steps change nothing a snapshot reads: nothing to leave unlisted")
    assert check(sample, tmp_path / "again", monkeypatch, profile_steps=unlisted)


def test_a_step_that_drops_a_value_fails_the_gate(tmp_path, monkeypatch):
    """A step that loses a stored value is not covered by any listed change: the gate fails on it."""
    def drop_a_company(folder):
        path = folder / "companies.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["companies"].pop()
        path.write_text(json.dumps(data), encoding="utf-8")

    steps = [*migrations.PROFILE_STEPS, Step("drops a company", drop_a_company, changes=("show_profile.config.*",))]
    sample = _newest()
    found = check(sample, tmp_path / "home", monkeypatch, profile_steps=steps)
    assert any(line.startswith("list_companies") for line in found)
