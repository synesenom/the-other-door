"""`compile` reads each PDF back as an ATS would (#357): `readable` on the entry, never a failed compile."""

import json

import pytest

from door.commands import compile as compile_cmd
from door.core import workspace
from door.tailoring import readability
from pdf_utils import make_pdf


@pytest.fixture
def job(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "config.json").write_text(json.dumps({"name": "Jane Doe"}))
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    jobs = tmp_path / "jobs"
    out = jobs / "output" / "job1"
    out.mkdir(parents=True)

    def fake_compilers(tex_path, output_dir, entry):
        make_pdf(tex_path.with_suffix(".pdf"), ["Jane Doe resume with enough text to count as readable text"])
        entry.update(status="compiled", pdf=str(tex_path.with_suffix(".pdf")), compiler="tectonic")

    monkeypatch.setattr(compile_cmd, "_run_compilers", fake_compilers)
    return jobs, out


def test_cv_and_letter_get_readable(job):
    jobs, out = job
    (out / "cv.tex").write_text("% Keywords: Kubernetes\n\\section{Experience}\n")
    (out / "cover_letter.tex").write_text("Dear team\n")
    cv, letter = compile_cmd._compile_core("job1", jobs_dir=jobs)["results"]
    details = " ".join(p["detail"] for p in cv["readable"])
    assert "Kubernetes" in details and "Experience" in details
    assert letter["readable"] == []  # no sections, no keywords, the name is there


def test_a_failing_check_is_a_warning_not_a_failed_compile(job, monkeypatch):
    jobs, out = job
    (out / "cv.tex").write_text("x")

    def boom(*a, **kw):
        raise RuntimeError("no pdf")

    monkeypatch.setattr(readability, "check_pdf", boom)
    cv = compile_cmd._compile_core("job1", jobs_dir=jobs)["results"][0]
    assert cv["status"] == "compiled" and cv["readable"] is None and "no pdf" in cv["warning"]


def test_errored_and_skipped_entries_have_no_readable(job, monkeypatch):
    jobs, out = job
    (out / "cv.tex").write_text("x")
    monkeypatch.setattr(compile_cmd, "_run_compilers", lambda t, o, e: e.update(status="error", stderr="bad"))
    cv, letter = compile_cmd._compile_core("job1", jobs_dir=jobs)["results"]
    assert "readable" not in cv and letter == {"file": "cover_letter.tex", "status": "skipped"}
