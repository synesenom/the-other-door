"""Live matcher golden regression test (issue #153, smoke layer).

Opt-in (marked `live`): spends real Claude Pro/Max plan usage, one `claude -p`
request per golden posting (via `door.matching.scorer.score_postings`).
Run explicitly with `./scripts/run-test.sh --live` (or `pytest -m live`).

This is the regression check the whole issue is about: nothing else in the
suite measures scoring *quality* — a rubric edit, a model swap, or a
condensing bug would otherwise only be noticed by a human seeing odd
rankings weeks later. Each golden posting (`tests/matching/fixtures/golden/*.json`)
carries a hand-labelled `[score_min, score_max]` band and an exact expected
`language_requirement`; bands are wide enough to absorb normal model
variance but narrow enough that a flipped verdict (e.g. an obvious mismatch
scoring above its band) fails.
"""

from __future__ import annotations

import json
import shutil

import pytest

from door.matching import scorer

from golden_utils import load_golden_cases
from paths import GOLDEN_PROFILE_DIR



def _case_passes(result: dict | None, expect: dict) -> bool:
    if result is None:
        return False
    score = result.get("score")
    if score is None or not (expect["score_min"] <= score <= expect["score_max"]):
        return False
    return result.get("language_requirement") == expect["language_requirement"]


_CASES = load_golden_cases()


def _case_id(case: dict) -> str:
    """The posting's id without its ``golden-`` prefix: the parameter scripts/smoke_report.py lists."""
    return case["posting"]["id"].removeprefix("golden-")


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        shutil.which("claude") is None,
        reason="`claude` CLI not on PATH; the golden set scores via a Pro/Max plan (local only, not CI)",
    ),
]


@pytest.fixture(scope="module")
def scored() -> tuple[dict, list]:
    """Every golden posting scored once, in parallel, by the real scorer: ``(results, failed)``."""
    profile_dir = GOLDEN_PROFILE_DIR
    config = json.loads((profile_dir / "config.json").read_text())
    cv_md = (profile_dir / "cv.md").read_text()
    system_prompt = scorer.build_system_prompt(config, cv_md, scorer.load_rubric_md())
    return scorer.score_postings(
        [c["posting"] for c in _CASES],
        system_prompt=system_prompt,
        model=scorer.DEFAULT_MODEL,
        workers=4,
        chunk=1,
    )


@pytest.mark.parametrize("case", _CASES, ids=_case_id)
def test_golden_case(case, scored):
    """One row per case on the live-smoke page's Matcher list: its score in its band, its language verdict exact."""
    results, failed = scored
    job_id = case["posting"]["id"]
    expect = case["expect"]
    result = results.get(job_id)
    assert job_id not in failed, f"scorer failed to score {job_id}"
    assert _case_passes(result, expect), (
        f"{job_id}: score={result.get('score') if result else None} "
        f"band=[{expect['score_min']:.2f}, {expect['score_max']:.2f}] "
        f"lang={result.get('language_requirement') if result else None} "
        f"expect_lang={expect['language_requirement']}"
    )
