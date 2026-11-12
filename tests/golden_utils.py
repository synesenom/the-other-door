"""Shared loader for the matcher golden regression set (issue #153).

Not a test module itself (no `test_` prefix, so pytest does not collect it) —
imported by `tests/matching/test_matcher_golden.py` (live) and
`tests/matching/test_matcher_golden_condense.py` (offline) so the fixture-loading
logic lives in exactly one place.
"""

from __future__ import annotations

import json
from pathlib import Path

from paths import GOLDEN_DIR

VALID_LANGUAGE_REQUIREMENTS = ("required", "advantage", "none")


def golden_case_paths() -> list[Path]:
    """Every `tests/matching/fixtures/golden/*.json` file, sorted for determinism."""
    return sorted(GOLDEN_DIR.glob("*.json"))


def load_golden_cases() -> list[dict]:
    """Load every golden case file as `{"path", "posting", "expect"}`."""
    cases = []
    for path in golden_case_paths():
        data = json.loads(path.read_text(encoding="utf-8"))
        cases.append({"path": path, "posting": data["posting"], "expect": data["expect"]})
    return cases
