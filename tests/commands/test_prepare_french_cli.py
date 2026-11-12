"""`prepare` on a saved French ad (#389): the tailor is patched to write a faithful French CV and letter on the
shipped templates, compiled for real when a LaTeX compiler is installed; the facts check finds nothing to report."""

import json
import shutil

import pytest

from door.commands import compile as compile_cmd
from door.commands import prepare as prepare_cmd
from door.core import installers
from tests.cli_utils import write_list_posting, write_tailor_outputs
from tests.paths import REPO_ROOT, TESTS_DIR
from pdf_utils import page_count, page_text

FRENCH = TESTS_DIR / "tailoring" / "fixtures" / "french"
EXAMPLE = REPO_ROOT / "profile.example"
JOB = "jobindex.fr-resp-ventes"


def _document(template: str, body: str) -> str:
    head, end, tail = (EXAMPLE / template).read_text(encoding="utf-8").rpartition("\\end{document}")
    return head + body + "\n" + end + tail


def _french_tailor(jobs_dir, *, compile_pdfs):
    def _run(job_id, posting_path, **kwargs):
        out = jobs_dir / "output" / job_id
        write_tailor_outputs(out)
        (out / "posting.json").write_text(posting_path.read_text(encoding="utf-8"), encoding="utf-8")
        (out / "cv.tex").write_text(_document("cv.template.tex", (FRENCH / "cv_body.tex").read_text(encoding="utf-8")), encoding="utf-8")
        (out / "cover_letter.tex").write_text(_document("cover-letter.template.tex", (FRENCH / "letter_body.tex").read_text(encoding="utf-8")), encoding="utf-8")
        if compile_pdfs:
            result = compile_cmd._compile_core(job_id, render=True, jobs_dir=jobs_dir)
            assert [r["status"] for r in result["results"]] == ["compiled", "compiled"], result
            assert [r["page_count"] for r in result["render"]] == [1, 1]
        return True

    return _run


def _seed(cli_env):
    ad = json.loads((FRENCH / "ad.json").read_text(encoding="utf-8"))
    ad["id"] = JOB
    write_list_posting(cli_env.jobs_dir, "2026-10-29", "jobindex", JOB, score=0.9, **{k: v for k, v in ad.items() if k != "id"})
    shutil.copy(FRENCH / "cv.md", cli_env.profile_dir / "cv.md")


def test_a_faithful_french_draft_has_nothing_unsupported(cli_env, monkeypatch):
    _seed(cli_env)
    monkeypatch.setattr(prepare_cmd, "_run_tailor", _french_tailor(cli_env.jobs_dir, compile_pdfs=False))

    result = prepare_cmd._prepare_core(JOB, jobs_dir=cli_env.jobs_dir)

    assert result["outcome"] == "prepared"
    assert result["unsupported"] == []


def test_an_invented_french_figure_is_reported_once(cli_env, monkeypatch):
    _seed(cli_env)
    tailor = _french_tailor(cli_env.jobs_dir, compile_pdfs=False)

    def invented(job_id, posting_path, **kwargs):
        tailor(job_id, posting_path)
        cv = cli_env.jobs_dir / "output" / job_id / "cv.tex"
        cv.write_text(cv.read_text(encoding="utf-8").replace("14 personnes", "40\\,000 personnes"), encoding="utf-8")
        return True

    monkeypatch.setattr(prepare_cmd, "_run_tailor", invented)
    result = prepare_cmd._prepare_core(JOB, jobs_dir=cli_env.jobs_dir)
    assert [(c["kind"], c["value"]) for c in result["unsupported"]] == [("number", "40000")]


@pytest.mark.skipif(
    installers.find_tectonic() is None and shutil.which("xelatex") is None, reason="needs Tectonic or xelatex"
)
def test_prepare_gives_a_compiled_one_page_french_cv_and_letter(cli_env, monkeypatch):
    _seed(cli_env)
    monkeypatch.setattr(prepare_cmd, "_run_tailor", _french_tailor(cli_env.jobs_dir, compile_pdfs=True))

    result = prepare_cmd._prepare_core(JOB, jobs_dir=cli_env.jobs_dir)

    assert result["outcome"] == "prepared" and result["unsupported"] == []
    out = cli_env.jobs_dir / "output" / JOB
    assert page_count(out / "cv.pdf") == page_count(out / "cover_letter.pdf") == 1
    cv_text = " ".join(page_text(out / "cv.pdf").split())
    letter_text = " ".join(page_text(out / "cover_letter.pdf").replace("\u00a0", " ").replace("\u202f", " ").split())
    assert "Formation" in cv_text and "Compétences" in cv_text and "Langues" in cv_text
    assert "Objet" in letter_text and "Madame, Monsieur," in letter_text and "« Ensemble" in letter_text
