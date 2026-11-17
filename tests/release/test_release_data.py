"""The release gate (#57): every earlier release's saved data opens in this build and reads back as it did.

Run by `./scripts/run-test.sh --release` (marker `release`), not by the offline suite or CI: between releases `main`
may not read the last release's data until `/dev-release` has written the upgrade step (#56).
"""

import json

import pytest

from door import version
from door.core import migrations
from door.core.migrations import Step
import release_gate_utils as gate
from release_gate_utils import check, check_refused, is_older_major, open_release, release_data, releases, sample_major, samples

pytestmark = pytest.mark.release

SAMPLES = releases()


def test_there_is_a_saved_release():
    """Of any major: a release that bumps the major keeps the older samples until after its tag (dev-release 6b)."""
    assert SAMPLES, "tests/data_versions/ holds no release: scripts/save_release_data.py X.Y.Z saves one"


@pytest.mark.parametrize("sample", samples(), ids=lambda p: p.relative_to(gate.SAMPLES_DIR).as_posix())
def test_a_saved_release_upgrades_and_reads_back_equal(sample, tmp_path, monkeypatch):
    """Each release's own sample, and its `default/` variant (the default profile: templates from the code, #141)."""
    found = check(sample, tmp_path / "home", monkeypatch)
    assert not found, f"{sample.relative_to(gate.SAMPLES_DIR)}'s data reads back differently:\n" + "\n".join(found)


def test_every_read_change_covers_a_difference_of_its_own_release(tmp_path, monkeypatch):
    """A `READ_CHANGES` key is a saved release, and that sample itself reads the path back differently; a key of an
    older major is left alone (its samples are only refused, until `/dev-release` deletes them with the entries)."""
    by_name = {s.name: s for s in SAMPLES}
    wrong = []
    for n, (version, entries) in enumerate(gate.READ_CHANGES.items()):
        sample = by_name.get(version)
        if sample is None:
            wrong.append(f"{version}: no saved release of that version")
            continue
        if is_older_major(sample):
            continue
        status, now, _ = open_release(sample, tmp_path / f"home{n}", monkeypatch)
        expected = json.loads((sample / "expected.json").read_text(encoding="utf-8"))
        found = {line.split(": ", 1)[0] for line in release_data.differences(expected, now)} if status is None else set()
        wrong += [f"{version}: {path} reads back the same: remove it" for path, _ in entries if path not in found]
    assert not wrong, "\n".join(wrong)


def test_a_read_change_excuses_its_difference_and_nothing_else(tmp_path, monkeypatch):
    sample = _newest()
    monkeypatch.setattr(gate, "READ_CHANGES", {})
    found = check(sample, tmp_path / "bare", monkeypatch)
    if not found:
        pytest.skip("the newest sample reads back equal: no read change to excuse")
    path = found[0].split(": ", 1)[0]
    monkeypatch.setattr(gate, "READ_CHANGES", {sample.name: ((path, "#0: test"),)})
    assert check(sample, tmp_path / "listed", monkeypatch) == found[1:]


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
    monkeypatch.setattr(gate, "READ_CHANGES", {})  # a read change excuses its difference too: leave none
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
