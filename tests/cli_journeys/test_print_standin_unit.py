"""The test world's stand-in for the Chromium print (app/test/world/print_standin.py, #146): real PDFs whose page
count follows the text, `worldfail` fails as a print does, and door's own `compile` reads them back clean."""

import json
import subprocess
import sys

import pytest

from door.commands import compile as compile_cmd
from door.core import chromium, workspace
from door.tailoring import html_pdf, pdf_render
from paths import REPO_ROOT

WORLD_DIR = REPO_ROOT / "app" / "test" / "world"


@pytest.fixture
def standin(monkeypatch):
    monkeypatch.syspath_prepend(str(WORLD_DIR))
    import print_standin

    monkeypatch.setattr(html_pdf, "print_html", html_pdf.print_html)  # restored after install()
    monkeypatch.setattr(chromium, "find_chromium", chromium.find_chromium)
    print_standin.install()
    return print_standin


def _print(standin, tmp_path, html, name="out"):
    out = tmp_path / f"{name}.pdf"
    standin.print_html(tmp_path, html, out)
    return out


def test_the_page_count_grows_with_the_text(standin, tmp_path):
    short = _print(standin, tmp_path, "<html><body><p>a few words</p></body></html>", "short")
    long = _print(standin, tmp_path, "<html><body>" + "<p>" + "forecasting " * 700 + "</p></body></html>", "long")
    assert len(pdf_render.page_texts(short)) == 1
    assert len(pdf_render.page_texts(long)) >= 2


def test_a_heading_is_on_a_line_of_its_own_and_a_list_item_has_a_bullet(standin, tmp_path):
    pdf = _print(standin, tmp_path, "<style>p{}</style><body><h2>Experience</h2><ul><li>Built things</li></ul><p>Tail</p></body>")
    lines = pdf_render.page_texts(pdf)[0].splitlines()
    assert "Experience" in lines and any(line.strip().startswith("•") and "Built things" in line for line in lines)
    assert "p{}" not in "".join(lines)  # the style is not text


def test_worldfail_is_a_print_error(standin, tmp_path):
    with pytest.raises(html_pdf.PrintError, match="worldfail"):
        _print(standin, tmp_path, "<body><p>worldfail</p></body>")


def test_install_replaces_the_print_and_the_chromium_lookup(standin):
    assert html_pdf.print_html is standin.print_html
    assert chromium.find_chromium()  # a path: the wrapper on PATH, else the interpreter


def test_the_wrapper_answers_version_the_way_doctor_asks(tmp_path):
    out = subprocess.run([sys.executable, str(WORLD_DIR / "print_standin.py"), str(tmp_path), "--version"],
                         capture_output=True, text=True)
    assert out.returncode == 0 and "Chromium" in out.stdout


def test_compile_through_the_stand_in_gives_pdfs_the_readback_finds_clean(standin, tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "config.json").write_text(json.dumps({"name": "Ada Lovelace"}))
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    out = tmp_path / "jobs" / "output" / "job"
    out.mkdir(parents=True)
    (out / "posting.json").write_text(json.dumps({"title": "Analyst", "company": "Acme", "location": "Aarhus"}))
    (out / "cv.html").write_text("<!-- Keywords: forecasting -->\n<header class=\"cv-header\"><h1>Ada Lovelace</h1></header>\n"
                                 "<h2>Experience</h2><p>Ada Lovelace led forecasting for the <<company>> finance team.</p>")
    (out / "cover_letter.html").write_text("<p>Dear team, I am Ada Lovelace and I want the <<title>> role.</p>")
    results = compile_cmd._compile_core("job", render=True, jobs_dir=tmp_path / "jobs")
    assert [r["status"] for r in results["results"]] == ["compiled", "compiled"]
    assert [r["readable"] for r in results["results"]] == [[], []]
    assert (out / "cv.pdf").is_file() and (out / "cv_page_1.png").is_file()


def test_a_world_body_with_worldfail_fails_compile_with_its_words(standin, tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "profile")
    out = tmp_path / "jobs" / "output" / "job"
    out.mkdir(parents=True)
    (out / "cv.html").write_text("<p>worldfail</p>")
    cv = compile_cmd._compile_core("job", jobs_dir=tmp_path / "jobs")["results"][0]
    assert cv["status"] == "error" and "worldfail" in cv["stderr"]
