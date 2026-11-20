"""`check_facts`: the tailor agent's offline fact check, at most two rounds per prepare run."""

import json

import pytest

from door.commands import check_facts as check_facts_cmd
from door.core import workspace
from door.tailoring import facts


@pytest.fixture
def world(tmp_path, monkeypatch):
    profile, jobs = tmp_path / "profile", tmp_path / "jobs"
    profile.mkdir()
    out = jobs / "output" / "job-abc"
    out.mkdir(parents=True)
    (profile / "cv.md").write_text("### Dev | Acme - 2019\n- Team of 12\n", encoding="utf-8")
    (out / "cv.html").write_text("<ul><li>Cut churn by 40%</li></ul>\n", encoding="utf-8")
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs)
    return profile, jobs, out


@pytest.fixture
def model(monkeypatch):
    state = {"calls": 0, "answer": {"findings": [{"kind": "number", "value": "40%", "context": "Cut churn by 40%", "file": "cv"}]}}

    def ask(inputs):
        state["calls"] += 1
        if isinstance(state["answer"], Exception):
            raise state["answer"]
        return state["answer"]

    monkeypatch.setattr(facts, "_ask", ask)
    return state


def _core(job="job-abc", **kw):
    return check_facts_cmd._check_facts_core(job, jobs_dir=workspace.JOBS_DIR, **kw)


def test_reports_unsupported_and_rounds(world, model):
    _, _, out = world
    first = _core()
    assert first["job_id"] == "job-abc" and first["round"] == 1 and first["rounds_left"] == 1
    assert [i["value"] for i in first["unsupported"]] == ["40%"]
    assert first["unsupported"] == facts.load(out)


def test_keep_persists_reason_with_no_second_call_and_no_round(world, model):
    _, _, out = world
    _core()
    result = _core(keep=[{"value": "40%", "kind": "number", "file": "cv", "reason": "from the ad"}])
    assert result["unsupported"][0]["reason"] == "from the ad"
    assert facts.load(out)[0]["reason"] == "from the ad"
    assert model["calls"] == 1 and result["round"] == 1 and result["rounds_left"] == 1


def test_a_changed_document_uses_the_second_round_and_the_third_is_refused(world, model):
    _, _, out = world
    _core()
    (out / "cv.html").write_text("<ul><li>Cut churn by 40% in a year</li></ul>\n", encoding="utf-8")
    assert _core()["round"] == 2
    (out / "cv.html").write_text("<ul><li>Cut churn by 40% in a month</li></ul>\n", encoding="utf-8")
    before = (out / "facts.json").read_text(encoding="utf-8")
    result = _core()
    assert "error" in result and model["calls"] == 2
    assert (out / "facts.json").read_text(encoding="utf-8") == before


def test_the_same_inputs_are_free_after_the_rounds_are_spent(world, model):
    _, _, out = world
    _core()
    (out / "cv.html").write_text("<ul><li>Cut churn by 40% in a year</li></ul>\n", encoding="utf-8")
    _core()
    assert _core()["round"] == 2 and model["calls"] == 2


def test_a_failed_call_is_not_checked_and_uses_no_round(world, model):
    from door.core import claude_cli

    model["answer"] = claude_cli.ClaudeError("limit")
    result = _core()
    assert result["unsupported"] is None and result["round"] == 0 and result["rounds_left"] == 2


def test_bad_job_ids(world):
    with pytest.raises(ValueError):
        _core("../evil")
    with pytest.raises(FileNotFoundError):
        check_facts_cmd._check_facts_core("job-zzz", jobs_dir=workspace.JOBS_DIR)
