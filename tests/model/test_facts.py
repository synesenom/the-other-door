"""`tailoring/facts.check` asked of the real Haiku on the local claude's plan (#433, epic #428).

Not in the offline suite or CI (marker `model`): `./scripts/run-test.sh --model`, before a release. Each case is one of the
spike's made-up facts cases (`scripts/record_cv_reading.py`: every language, with fabrications planted in the tailored
CV or letter): checked through the real model, every planted kind is found, every finding is words of its document, and a
second check of the same files asks nothing."""

import importlib.util

import pytest

from conftest import claude_ready
from door.tailoring import facts
from paths import REPO_ROOT

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def corpus():
    spec = importlib.util.spec_from_file_location("record_cv_reading", REPO_ROOT / "scripts" / "record_cv_reading.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_body_corpus()


@pytest.mark.parametrize("index", [0, 5, 20])
def test_the_real_model_finds_the_planted_claims_and_the_cache_serves_the_second_check(index, corpus, tmp_path, monkeypatch):
    if reason := claude_ready():
        pytest.skip(reason)
    case = sorted(corpus)[index]
    data = corpus[case]
    out, prof = tmp_path / "out", tmp_path / "profile"
    out.mkdir(), prof.mkdir()
    (prof / "cv.md").write_text(data["md"], encoding="utf-8")
    (prof / "story_bank.md").write_text(data["story"], encoding="utf-8")
    (out / "cv.html").write_text(data["body"], encoding="utf-8")
    (out / "cover_letter.html").write_text(data["letter"], encoding="utf-8")
    (out / "posting.json").write_text('{"title": "Role", "description": %s}' % __import__("json").dumps(data["posting"]), encoding="utf-8")
    found = facts.check(out, prof)
    assert found is not None
    for plant in data["plants"]:
        assert any(f["kind"] == plant["kind"] for f in found), plant
    monkeypatch.setattr(facts, "_ask", lambda inputs: pytest.fail("the second check asks nothing"))
    assert facts.check(out, prof) == found
