"""/upskill, run by the real model on the local plan against the app's test world (#33).

Marker `skills`, never CI. Two runs: "top 3" and one named by company words. Checks are on behaviour: the
profile is checked before the analysis, the target is passed as the skill says, the report is written,
and nothing else (no find, no prepare, no profile change) happens.
"""

import pytest

from conftest import home, run_skill

pytestmark = pytest.mark.skills

NOT_ASKED_FOR = ("find_jobs", "prepare", "init_profile", "set_status", "import_posting", "revise",
                "mark_reviewed")


@pytest.fixture(scope="module")
def top(tmp_path_factory):
    return run_skill(tmp_path_factory, "upskill-top", "/upskill top 3", max_turns=5, stop_after_tool="skill_gaps",
                     persona_kind="onboarded")


@pytest.fixture(scope="module")
def one_job(tmp_path_factory):
    return run_skill(tmp_path_factory, "upskill-job", "/upskill the Baltic Power Trading one", max_turns=6,
                     stop_after_tool="skill_gaps", persona_kind="onboarded",
                     facts_note="You mean the Baltic Power Trading job; if several jobs match, pick the first.")


def _gap_calls(result):
    return [c for c in result["calls"] if c["tool"] == "skill_gaps"]


def test_it_checks_the_profile_before_the_analysis_and_passes_the_top_count(top):
    _, result = top
    tools = result["tools"]
    assert tools.index("doctor") < tools.index("skill_gaps"), tools
    assert _gap_calls(result)[0]["args"].get("top") == 3, _gap_calls(result)


def test_it_passes_a_named_job_as_a_job_not_as_a_role(one_job):
    _, result = one_job
    calls = _gap_calls(result)
    assert calls, result["tools"]
    args = calls[-1]["args"]
    assert args.get("jobs"), args
    assert not args.get("targets"), args


def test_the_report_is_written_with_its_plan(top):
    world, _ = top
    reports = sorted((home(world) / "upskill").glob("report-*.md"))
    assert reports, "no upskill/report-*.md"
    assert "### 1." in reports[-1].read_text(encoding="utf-8")


def test_nothing_else_is_done_and_no_shell_or_write_is_used(top, one_job):
    for _, result in (top, one_job):
        assert not [t for t in result["tools"] if t in NOT_ASKED_FOR], result["tools"]
        assert not [u for u in result["used"] if u["tool"] in ("Bash", "Write", "Edit")], result["used"]
