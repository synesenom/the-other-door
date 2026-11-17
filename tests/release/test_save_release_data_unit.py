"""`scripts/save_release_data.py` (#141): a release's sample and its `default/` variant are each saved when missing, so a
rerun after a save that failed half way saves only what is not there; one already saved is never overwritten."""

import importlib.util

import pytest

from paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("save_release_data", REPO_ROOT / "scripts" / "save_release_data.py")
srd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srd)


@pytest.fixture
def saved(tmp_path, monkeypatch):
    """The variants saved by a `save` call (git and the tag's code stood in)."""
    calls = []
    monkeypatch.setattr(srd, "SAMPLES", tmp_path)
    monkeypatch.setattr(srd, "run", lambda cmd, **kw: "")

    def fake(tree, scratch, target, variant):
        calls.append(variant)
        (target / "profile").mkdir(parents=True, exist_ok=True)
        (target / "expected.json").write_text("{}")

    monkeypatch.setattr(srd, "_save_variant", fake)
    return calls


def _write(folder):
    (folder / "profile").mkdir(parents=True)
    (folder / "expected.json").write_text('{"kept": true}')


def test_a_new_release_saves_both_variants(tmp_path, saved):
    srd.save("1.2.3")
    assert saved == ["full", "default"]
    assert (tmp_path / "1.2.3" / "expected.json").is_file() and (tmp_path / "1.2.3" / "default" / "expected.json").is_file()


def test_a_release_saved_without_its_default_variant_gets_only_that(tmp_path, saved):
    _write(tmp_path / "1.2.3")
    srd.save("1.2.3")
    assert saved == ["default"]
    assert (tmp_path / "1.2.3" / "expected.json").read_text() == '{"kept": true}'


def test_a_variant_left_half_written_is_saved_again(tmp_path, saved):
    _write(tmp_path / "1.2.3")
    (tmp_path / "1.2.3" / "default" / "profile").mkdir(parents=True)  # no expected.json: the save stopped there
    srd.save("1.2.3")
    assert saved == ["default"]


def test_a_release_with_both_variants_is_refused(tmp_path, saved):
    _write(tmp_path / "1.2.3")
    _write(tmp_path / "1.2.3" / "default")
    with pytest.raises(SystemExit, match="exists"):
        srd.save("1.2.3")
    assert saved == []
