"""`core/cv_read` asked of the real Haiku on the local claude's plan (#430, epic #428).

Not in the offline suite or CI (marker `model`): `./scripts/run-test.sh --model`, before a release. Each case is one of the
spike's made-up CVs (`scripts/record_cv_reading.py`: every language, heading and contact style): read through the real
model and held to `cv_read.check`, the sections' kinds against what the corpus knows, a second read asking nothing."""

import importlib.util

import pytest

from conftest import claude_ready
from door.core import cv_read
from paths import REPO_ROOT

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def corpus():
    spec = importlib.util.spec_from_file_location("record_cv_reading", REPO_ROOT / "scripts" / "record_cv_reading.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_reader_corpus()


@pytest.mark.parametrize("name", ["p00-da", "p01-fr", "p03-da"])
def test_the_real_model_reads_a_cv_and_the_cache_serves_the_second_read(name, corpus, tmp_path, monkeypatch):
    if reason := claude_ready():
        pytest.skip(reason)
    monkeypatch.setattr(cv_read, "_cache_dir", lambda: tmp_path / "cache")
    md = corpus[name]["md"]
    first = cv_read.read(md)
    assert first["name"] and {s["kind"] for s in first["sections"]} >= {"experience", "education"}
    monkeypatch.setattr(cv_read, "_ask", lambda md: pytest.fail("the second read asks nothing"))
    assert cv_read.read(md) == first
