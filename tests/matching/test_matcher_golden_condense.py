"""Offline half of the matcher golden set (issue #153).

Two things run here, both offline (no network, no LLM) and both part of the
default `./scripts/run-test.sh` suite:

1. A sanity check that every `tests/matching/fixtures/golden/*.json` file is valid
   JSON with the required `posting`/`expect` keys, and that
   `expect.language_requirement` is one of `SCORE_SCHEMA`'s three enum
   values (`"required"|"advantage"|"none"`).
2. A regression guard for `door.matching.condense.condense_description`:
   runs each golden posting's `description` through it and asserts that the
   "always-keep" signal sentence for the relevant category survives — the
   Danish-requirement posting's requirement sentence, the Danish-advantage
   posting's advantage sentence, the salary posting's salary sentence, and
   the remote/hybrid posting's remote sentence. This is what would have
   caught #143's own worked example (a bug that drops a requirement
   sentence) without spending any plan quota.
"""

from __future__ import annotations

import json

import pytest

from door.matching.condense import condense_description, extract_skill_terms

from golden_utils import (
    VALID_LANGUAGE_REQUIREMENTS,
    golden_case_paths,
    load_golden_cases,
)
from paths import GOLDEN_PROFILE_DIR

_REQUIRED_POSTING_FIELDS = {"id", "title", "company", "location", "url", "description"}


# --------------------------------------------------------------------------- #
# Fixture-validity sanity check
# --------------------------------------------------------------------------- #


def test_golden_fixtures_are_well_formed():
    paths = golden_case_paths()
    assert len(paths) >= 12, "expected at least 12 golden cases per issue #153"
    ids = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = _REQUIRED_POSTING_FIELDS - data["posting"].keys()
        assert not missing, f"{path}: posting missing fields {missing}"
        expect = data["expect"]
        assert 0.0 <= expect["score_min"] <= expect["score_max"] <= 1.0, f"{path}: invalid score band"
        assert expect["language_requirement"] in VALID_LANGUAGE_REQUIREMENTS, path
        ids.append(data["posting"]["id"])
    assert len(ids) == len(set(ids)), f"duplicate golden posting ids: {ids}"


# --------------------------------------------------------------------------- #
# condense_description regression guard
# --------------------------------------------------------------------------- #


def _realistic_keep_terms() -> set:
    """The keep_terms a real `match` run would use (the golden profile's CV + config)."""
    config = json.loads((GOLDEN_PROFILE_DIR / "config.json").read_text())
    cv_md = (GOLDEN_PROFILE_DIR / "cv.md").read_text()
    return extract_skill_terms(cv_md, config)


@pytest.mark.parametrize(
    "job_id, sentence",
    [
        ("golden-danish-required", "you must speak and write fluent Danish"),
        ("golden-danish-advantage", "Danish is an advantage but not required"),
        ("golden-salary-stated", "750,000-850,000 DKK per year"),
        ("golden-remote-global", "This role is fully remote"),
    ],
)
def test_condense_keeps_the_signal_sentence(job_id, sentence):
    """The always-keep sentence survives with no keep_terms and with a real
    profile's keep_terms alike: it is matched independently of the term list."""
    description = {c["posting"]["id"]: c["posting"] for c in load_golden_cases()}[job_id]["description"]
    assert sentence in condense_description(description, keep_terms=set())
    assert sentence in condense_description(description, keep_terms=_realistic_keep_terms())
