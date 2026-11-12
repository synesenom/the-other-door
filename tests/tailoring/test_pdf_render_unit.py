"""Unit tests for tailoring/pdf_render.py — offline, no network."""

import pathlib
import pytest

from pdf_utils import make_pdf


def _make_pdf(path: pathlib.Path, num_pages: int = 1) -> pathlib.Path:
    """Create a minimal PDF with *num_pages* blank pages at *path*."""
    return make_pdf(path, [""] * num_pages)


# ---------------------------------------------------------------------------
# get_page_count
# ---------------------------------------------------------------------------


def test_get_page_count_returns_correct_int(tmp_path):
    """get_page_count returns the correct integer for a 2-page PDF."""
    from door.tailoring.pdf_render import get_page_count

    pdf = _make_pdf(tmp_path / "sample.pdf", num_pages=2)
    assert get_page_count(pdf) == 2


def test_get_page_count_file_not_found(tmp_path):
    """get_page_count raises FileNotFoundError for a missing file."""
    from door.tailoring.pdf_render import get_page_count

    missing = tmp_path / "does_not_exist.pdf"
    with pytest.raises(FileNotFoundError):
        get_page_count(missing)


# ---------------------------------------------------------------------------
# render_pdf_pages
# ---------------------------------------------------------------------------


def test_render_pdf_pages_writes_pngs(tmp_path):
    """render_pdf_pages creates one PNG per page with the expected filenames."""
    from door.tailoring.pdf_render import render_pdf_pages

    pdf = _make_pdf(tmp_path / "cv.pdf", num_pages=2)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = render_pdf_pages(pdf, out_dir)

    assert len(result) == 2
    assert result[0] == out_dir / "cv_page_1.png"
    assert result[1] == out_dir / "cv_page_2.png"
    for p in result:
        assert p.exists(), f"{p} was not created"
        assert p.stat().st_size > 0, f"{p} is empty"


def test_render_pdf_pages_file_not_found(tmp_path):
    """render_pdf_pages raises FileNotFoundError for a missing PDF."""
    from door.tailoring.pdf_render import render_pdf_pages

    missing = tmp_path / "ghost.pdf"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with pytest.raises(FileNotFoundError):
        render_pdf_pages(missing, out_dir)


# ---------------------------------------------------------------------------
# page counts surfaced by `compile --render` (issue #136)
# ---------------------------------------------------------------------------


def _output_dir_with_pdfs(tmp_path, cv_pages=2, letter_pages=1):
    out = tmp_path / "jobs" / "output" / "job1"
    out.mkdir(parents=True)
    _make_pdf(out / "cv.pdf", num_pages=cv_pages)
    _make_pdf(out / "cover_letter.pdf", num_pages=letter_pages)
    return tmp_path / "jobs"


def test_render_pages_reports_page_counts(tmp_path):
    from door.commands import compile as compile_cmd

    jobs_dir = _output_dir_with_pdfs(tmp_path, cv_pages=3, letter_pages=1)
    results = compile_cmd._render_pages(jobs_dir / "output" / "job1")
    assert [(r["file"], r["page_count"]) for r in results] == [("cv.pdf", 3), ("cover_letter.pdf", 1)]
