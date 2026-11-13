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
    (out / "cv.tex").write_text("\\begin{document}\n\\item Cut churn by 40\\%\n", encoding="utf-8")
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs)
    return profile, jobs, out


def _core(job="job-abc", **kw):
    return check_facts_cmd._check_facts_core(job, jobs_dir=workspace.JOBS_DIR, **kw)


def test_reports_unsupported_and_rounds(world):
    _, _, out = world
    first = _core()
    assert first["job_id"] == "job-abc" and first["round"] == 1 and first["rounds_left"] == 1
    assert [i["value"] for i in first["unsupported"]] == ["40%"]
    assert first["unsupported"] == facts.load(out)


def test_keep_persists_reason(world):
    _, _, out = world
    result = _core(keep=[{"value": "40%", "kind": "number", "file": "cv", "reason": "from the ad"}])
    assert result["unsupported"][0]["reason"] == "from the ad"
    assert facts.load(out)[0]["reason"] == "from the ad"


def test_third_call_is_refused_and_writes_nothing(world):
    _, _, out = world
    _core()
    _core()
    before = (out / "facts.json").read_text(encoding="utf-8")
    (out / "facts.json").write_text(before + " ", encoding="utf-8")
    result = _core()
    assert "error" in result
    assert (out / "facts.json").read_text(encoding="utf-8") == before + " "


def test_bad_job_ids(world):
    with pytest.raises(ValueError):
        _core("../evil")
    with pytest.raises(FileNotFoundError):
        check_facts_cmd._check_facts_core("job-zzz", jobs_dir=workspace.JOBS_DIR)


def test_check_that_cannot_run_consumes_no_round(world):
    profile, _, out = world
    (profile / "cv.md").unlink()
    for _ in range(3):
        assert _core() == {"job_id": "job-abc", "round": 0, "rounds_left": 2, "unsupported": None}
    assert not (out / ".facts_rounds").exists()
