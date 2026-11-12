"""The shipped LaTeX templates compile a French CV and letter (#389) without changing English output.

Compiles for real under Tectonic (or xelatex) and is skipped when none is installed.
"""

import shutil
from pathlib import Path

import pytest

from door import i18n
from door.commands import compile as compile_cmd
from door.core import installers
from door.tailoring import pdf_render, tex_guard
from tests.paths import REPO_ROOT, TESTS_DIR

FIXTURES = TESTS_DIR / "tailoring" / "fixtures" / "french"
EXAMPLE = REPO_ROOT / "profile.example"

needs_tex = pytest.mark.skipif(
    installers.find_tectonic() is None and shutil.which("xelatex") is None,
    reason="needs Tectonic or xelatex",
)


def _document(template: str, body: str) -> str:
    text = (EXAMPLE / template).read_text(encoding="utf-8")
    head, end, tail = text.rpartition("\\end{document}")  # the template's comments name it too
    return head + body + "\n" + end + tail


def _compile(tmp_path: Path, cv_body: str, letter_body: str) -> dict[str, str]:
    out = tmp_path / "output" / "job-fr"
    out.mkdir(parents=True)
    (out / "cv.tex").write_text(_document("cv.template.tex", cv_body), encoding="utf-8")
    (out / "cover_letter.tex").write_text(_document("cover-letter.template.tex", letter_body), encoding="utf-8")
    result = compile_cmd._compile_core("job-fr", jobs_dir=tmp_path)
    assert [(r["file"], r["status"]) for r in result["results"]] == [("cv.tex", "compiled"), ("cover_letter.tex", "compiled")], result
    texts = {}
    for name in ("cv", "cover_letter"):
        pages = pdf_render.page_texts(out / f"{name}.pdf")
        assert len(pages) == 1
        texts[name] = "".join(pages)
    return texts


def test_the_french_bodies_pass_the_tex_guard():
    for name in ("cv_body.tex", "letter_body.tex"):
        assert tex_guard.unsafe((FIXTURES / name).read_text(encoding="utf-8")) == []


@needs_tex
def test_a_french_cv_and_letter_compile_with_french_typography(tmp_path):
    texts = _compile(tmp_path, (FIXTURES / "cv_body.tex").read_text(encoding="utf-8"),
                     (FIXTURES / "letter_body.tex").read_text(encoding="utf-8"))
    cv = " ".join(texts["cv"].split())
    assert "Expérience" in cv and "Formation" in cv and "Compétences" in cv and "Langues" in cv
    letter = " ".join(texts["cover_letter"].replace("\u00a0", " ").replace("\u202f", " ").split())
    assert "« Ensemble, allons plus loin »" in letter
    assert "Lyon, le 29 octobre 2026" in letter
    assert "salutations distinguées" in letter


def _words(path: Path) -> list[str]:
    return pdf_render.page_texts(path)[0].split()


@needs_tex
def test_babel_french_is_on_in_a_french_letter_and_off_otherwise(tmp_path):
    """French sets a no-break space before : ; ! ? (so "Objet" and ":" are two words) and spells \\today in French."""
    words = "Objet: un! deux? trois; quatre."
    cv = "\\noindent\\today"
    _compile(tmp_path / "fr", "\\selectlanguage{french}" + cv, "\\selectlanguage{french}" + words)
    fr = _words(tmp_path / "fr" / "output" / "job-fr" / "cover_letter.pdf")
    assert "Objet" in fr and ":" in fr
    months = {name for name in i18n.month_numbers(("fr",)) if name.isalpha()}
    assert set(_words(tmp_path / "fr" / "output" / "job-fr" / "cv.pdf")) & months
    _compile(tmp_path / "en", cv, words)
    assert "Objet:" in _words(tmp_path / "en" / "output" / "job-fr" / "cover_letter.pdf")


@needs_tex
def test_english_danish_and_hungarian_letters_still_compile(tmp_path):
    body = "\\renewcommand{{\\today}}{{{date}}}\\renewcommand{{\\signoff}}{{{sign}}}\n\\letterheader{{A}}{{1}}{{a@x.dk}}{{x.dk}}{{C}}\n\\recipient{{X}}{{Y}}{{Z}}\nHej: verden! Mit csinálsz? Æ ø å, ő ű.\n\\closing{{A}}"
    for i, (date, sign) in enumerate([("11. oktober 2026", "Med venlig hilsen,"), ("2026. október 11.", "Üdvözlettel,"), ("October 11, 2026", "Kind regards,")]):
        cv = "\\cvheader{A}{1}{a@x.dk}{x.dk}{C}\n\\section{Profile}\nÆøå őű: text"
        _compile(tmp_path / str(i), cv, body.format(date=date, sign=sign))
