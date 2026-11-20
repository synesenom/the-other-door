"""`draft_cv` asked of the real Sonnet on the local claude's plan (#422).

Not in the offline suite or CI (marker `model`): `./scripts/run-test.sh --model`, before a release. One made-up CV with a
section outside the template ("Research & analyses", two sub-groups) and one titled in Danish ("Uddannelse") is drafted
once; the draft must keep both titles as written and the sub-groups as `###` lines."""

import re

import pytest

from conftest import claude_ready
from door.commands import cv as cv_cmd

pytestmark = pytest.mark.model

CV = """# Anna Example

anna.example@example.com | Aarhus, Denmark

## Profile

Data analyst with six years of experience in public-sector research.

## Erfaring

### Senior Analyst, Example Institute (2021 - 2024)

- Led a team of three analysts on yearly survey studies.
- Built reporting pipelines in Python and SQL.

### Analyst, Sample Agency (2018 - 2021)

- Produced monthly statistics for the ministry.

## Research & analyses

### Survey studies

- Household income survey, 2022: designed the sampling and weighting.
- Youth wellbeing panel, 2023: wrote the analysis plan.

### Policy evaluations

- Evaluation of a regional jobs programme, 2021.
- Cost-benefit analysis of a transport scheme, 2020.

## Uddannelse

- MSc in Statistics, Example University (2016 - 2018)
- BSc in Mathematics, Example University (2013 - 2016)
"""


def _headings(markdown: str, level: str) -> list[str]:
    return [" ".join(m.group(1).split()).casefold() for m in re.finditer(rf"^{level} (.+?)\s*$", markdown, re.M)]


@pytest.fixture(scope="module")
def draft(tmp_path_factory):
    if reason := claude_ready():
        pytest.skip(reason)
    folder = tmp_path_factory.mktemp("draft")
    source = folder / "cv.md"
    source.write_text(CV, encoding="utf-8")
    return cv_cmd._draft_cv_core([str(source)], profile_dir=folder / "profile")["markdown"]


def test_the_draft_keeps_a_section_outside_the_template_and_its_sub_groups(draft):
    assert "research & analyses" in _headings(draft, "##")
    assert {"survey studies", "policy evaluations"} <= set(_headings(draft, "###"))


def test_the_draft_keeps_a_section_titled_in_another_language(draft):
    assert "uddannelse" in _headings(draft, "##")
    assert "education" not in _headings(draft, "##")
