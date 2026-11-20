"""Unit tests for The other door's importable `_*_core` functions (issue #79).

These exercise the extracted core functions directly (no Click, no CliRunner)
so they can be reused by the MCP adapter as well as the CLI. Core functions
return structured data and raise ordinary exceptions instead of calling
`click.echo`/`sys.exit` — this is a hard requirement so that a stray print
never corrupts an MCP stdio JSON-RPC stream.
"""

import json
import sys
import types
from datetime import date
from pathlib import Path

import pytest

from door.commands import _common as common
from door.commands import compile as compile_cmd
from door.commands import scrape as scrape_cmd
from door.matching import condense, dedup, prefilter, prescreen
from cli_utils import scrape_and_pass
from profile_utils import write_config


def _scrape_env(tmp_path, sites=("jobindex",)):
    """Seed a profile_dir/config.json + empty jobs_dir under tmp_path."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    profile_dir_config = {
        "role_targets": ["data scientist"],
        "location": "Copenhagen",
    }
    write_config(profile_dir, profile_dir_config)
    jobs_dir = tmp_path / "jobs"
    return profile_dir, jobs_dir



# --------------------------------------------------------------------------- #
# _compile_core
# --------------------------------------------------------------------------- #

def test_compile_core_invalid_job_id_raises_value_error(tmp_path):
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()

    with pytest.raises(ValueError):
        compile_cmd._compile_core("../evil", jobs_dir=jobs_dir)


def test_compile_core_missing_output_dir_raises_file_not_found(tmp_path):
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()

    with pytest.raises(FileNotFoundError):
        compile_cmd._compile_core("nope", jobs_dir=jobs_dir)


# --------------------------------------------------------------------------- #
# _render_pages / compile --render
# --------------------------------------------------------------------------- #

def _inject_fake_pdf_render(monkeypatch, fake_render):
    pdf_render_mod = types.ModuleType("door.render.pdf_render")
    pdf_render_mod.render_pdf_pages = fake_render
    tailoring_pkg = types.ModuleType("tailoring")
    tailoring_pkg.pdf_render = pdf_render_mod
    monkeypatch.setitem(sys.modules, "tailoring", tailoring_pkg)
    monkeypatch.setitem(sys.modules, "door.render.pdf_render", pdf_render_mod)


def test_render_pages_missing_pdfs_are_skipped(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    out_dir = jobs_dir / "output" / "job1"
    out_dir.mkdir(parents=True)

    def _fake_render(pdf_path, output_dir):  # pragma: no cover — must not be called
        raise AssertionError("render_pdf_pages must not be called when no PDFs are present")

    _inject_fake_pdf_render(monkeypatch, _fake_render)

    results = compile_cmd._render_pages(out_dir)

    assert results == [
        {"file": "cv.pdf", "status": "skipped"},
        {"file": "cover_letter.pdf", "status": "skipped"},
    ]


def test_render_pages_renders_present_pdfs_in_order(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    out_dir = jobs_dir / "output" / "job1"
    out_dir.mkdir(parents=True)
    (out_dir / "cv.pdf").write_bytes(b"%PDF-stub")
    (out_dir / "cover_letter.pdf").write_bytes(b"%PDF-stub")

    calls = []

    def _fake_render(pdf_path, output_dir):
        calls.append(pdf_path)
        png = output_dir / f"{pdf_path.stem}_page_1.png"
        png.write_bytes(b"PNG")
        return [png]

    _inject_fake_pdf_render(monkeypatch, _fake_render)

    results = compile_cmd._render_pages(out_dir)

    assert calls == [out_dir / "cv.pdf", out_dir / "cover_letter.pdf"]
    assert results[0]["status"] == "rendered"
    assert results[0]["pages"] == [str(out_dir / "cv_page_1.png")]
    assert results[0]["page_count"] == 1
    assert results[1]["status"] == "rendered"
    assert results[1]["pages"] == [str(out_dir / "cover_letter_page_1.png")]


# --------------------------------------------------------------------------- #
# _scrape_core
# --------------------------------------------------------------------------- #

def test_scrape_core_happy_path_writes_postings_and_returns_counts(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path)

    import door.scrapers.boards.jobindex as ji
    posting = {
        "id": "jobindex-acme-data-scientist", "title": "Data Scientist",
        "company": "Acme", "location": "Copenhagen", "url": "https://x/1",
        "description": "We are looking for a data scientist who will join our team and work with Python.", "source": "jobindex", "scraped_at": "2026-06-13T00:00:00Z",
    }
    monkeypatch.setattr(ji, "scrape", lambda config, **kwargs: [posting])
    monkeypatch.delattr(ji, "iter_scrape", raising=False)

    result = scrape_cmd._scrape_core(["jobindex"], jobs_dir=jobs_dir, profile_dir=profile_dir)

    run_date = date.today().isoformat()
    out_dir = jobs_dir / "postings" / run_date / "jobindex"
    out_file = out_dir / "jobindex-acme-data-scientist.json"
    assert out_file.exists()
    assert json.loads(out_file.read_text())["company"] == "Acme"

    assert result["run_date"] == run_date
    assert result["sites"][0].pop("since")  # first scrape: the max_age_days cutoff
    assert result["sites"] == [{"site": "jobindex", "outcome": "ok", "count": 1, "stale": 0, "dir": str(out_dir), "errors": []}]
    assert result["candidates_dir"] == str(jobs_dir / "postings" / run_date)


def test_scrape_core_per_site_outcomes_preserved_in_order(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path, sites=("jobindex", "lever", "thehub"))
    write_config(profile_dir, {
        "role_targets": ["data scientist"],
        "location": "Copenhagen",
    })
    from door.core.employers import companies as _companies
    _items = _companies.load(profile_dir)
    _companies.record(_items, "Acme", feed=("lever", "acme"), status="followed", found_via="manual", reason=None)
    _companies.save(profile_dir, _items)

    import door.scrapers.boards.jobindex as ji
    posting = {
        "id": "jobindex-acme-x", "title": "X", "company": "Acme", "location": "CPH",
        "url": "u", "description": "We are looking for a data scientist who will join our team and work with Python.", "source": "jobindex", "scraped_at": "2026-06-13T00:00:00Z",
    }
    monkeypatch.setattr(ji, "scrape", lambda config, **kwargs: [posting])
    monkeypatch.delattr(ji, "iter_scrape", raising=False)

    import door.scrapers.boards.thehub as th

    def boom(config, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(th, "scrape", boom)

    result = scrape_cmd._scrape_core(
        ["jobindex", "thehub"], jobs_dir=jobs_dir, profile_dir=profile_dir,
    )

    outcomes = [(entry["site"], entry["outcome"]) for entry in result["sites"]]
    assert outcomes == [("jobindex", "ok"), ("thehub", "error")]
    assert result["sites"][1]["error"] == "kaboom"


def test_scrape_core_liveness_absent_is_none_and_not_called(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path)

    import door.scrapers.boards.jobindex as ji
    monkeypatch.setattr(ji, "scrape", lambda config, **kwargs: [])
    monkeypatch.delattr(ji, "iter_scrape", raising=False)

    from door.scrapers import liveness as liveness_mod

    def _should_not_be_called(paths, config):
        raise AssertionError("verify_liveness must NOT be called when flag is absent")

    monkeypatch.setattr(liveness_mod, "verify_liveness", _should_not_be_called)

    result = scrape_cmd._scrape_core(["jobindex"], jobs_dir=jobs_dir, profile_dir=profile_dir)

    assert result["liveness"] is None


def test_scrape_core_surviving_paths_reflect_dedup_output(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path)

    import door.scrapers.boards.jobindex as ji
    monkeypatch.setattr(ji, "scrape", lambda config, **kwargs: [])
    monkeypatch.delattr(ji, "iter_scrape", raising=False)

    monkeypatch.setattr(prefilter, "prefilter", lambda candidates_dir, config: ["a", "b"])
    monkeypatch.setattr(dedup, "dedup", lambda paths, config, aliases=None, earlier=None: paths[:1])
    # "a"/"b" are fake stand-in paths (no real files), so condense/prescreen
    # (which read the surviving JSON files from disk) are stubbed as no-ops
    # here — this test is only about the prefilter -> dedup wiring.
    monkeypatch.setattr(condense, "condense_postings", lambda paths, terms, config: {"count": len(paths), "avg_ratio": None})
    monkeypatch.setattr(condense, "extract_skill_terms", lambda reading, config: set())
    monkeypatch.setattr(prescreen, "prescreen", lambda paths, config, terms: paths)

    result = scrape_and_pass(profile_dir, jobs_dir, ["jobindex"])

    assert result["prefilter"] == {"survived": 2}
    assert result["dedup"] == {"collapsed": 1, "remaining": 1}
    assert result["surviving_paths"] == ["a"]


def test_scrape_core_dedups_with_the_names_companies_json_holds_for_one_employer(tmp_path, monkeypatch):
    from door.core.employers import companies as companies_store

    profile_dir, jobs_dir = _scrape_env(tmp_path)
    companies_store.save(profile_dir, [
        companies_store.Company(name="Flugger", feed={"platform": "successfactors", "id": "jobs.flugger.com"},
                                status="followed", found_via="manual", aliases=["Flügger group A/S"]),
        companies_store.Company(name="Acme", feed={"platform": "greenhouse", "id": "acme"},
                                status="followed", found_via="manual"),
    ])

    import door.scrapers.boards.jobindex as ji
    monkeypatch.setattr(ji, "scrape", lambda config, **kwargs: [])
    monkeypatch.delattr(ji, "iter_scrape", raising=False)
    monkeypatch.setattr(prefilter, "prefilter", lambda candidates_dir, config: [])
    seen = {}
    monkeypatch.setattr(dedup, "dedup", lambda paths, config, aliases=None, earlier=None: seen.setdefault("aliases", aliases) and paths)

    scrape_and_pass(profile_dir, jobs_dir, ["jobindex"])

    assert seen["aliases"] == [["Flugger", "Flügger group A/S"]]


# --------------------------------------------------------------------------- #
# _scrape_core — condense + prescreen (issue #143)
# --------------------------------------------------------------------------- #

def test_scrape_core_condense_and_prescreen_run_after_dedup(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path)

    import door.scrapers.boards.jobindex as ji
    posting = {
        "id": "jobindex-acme-data-scientist", "title": "Data Scientist",
        "company": "Acme", "location": "Copenhagen", "url": "https://x/1",
        "description": (
            "We build forecasting models for the business.\n\n"
            "Requirements:\n5+ years of experience with Python is required.\n\n"
            "About us:\nWe are a friendly workplace with free lunch and great coffee."
        ),
        "source": "jobindex", "scraped_at": "2026-06-13T00:00:00Z",
    }
    monkeypatch.setattr(ji, "scrape", lambda config, **kwargs: [posting])
    monkeypatch.delattr(ji, "iter_scrape", raising=False)

    result = scrape_and_pass(profile_dir, jobs_dir, ["jobindex"])

    assert result["condense"]["count"] == 1
    assert result["prescreen"]["scored"] == 1

    run_date = date.today().isoformat()
    out_file = jobs_dir / "postings" / run_date / "jobindex" / "jobindex-acme-data-scientist.json"
    data = json.loads(out_file.read_text())
    assert data["description_condensed"]
    assert "free lunch" not in data["description_condensed"].lower()
    assert "prescreen_score" in data


def test_scrape_core_prescreen_honours_config_top_n(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path)
    write_config(profile_dir, {
        "role_targets": ["data scientist"],
        "location": "Copenhagen",
        "prescreen_top_n": 1,
        "prescreen_min": 0.0,
    })

    import door.scrapers.boards.jobindex as ji
    postings = [
        {
            "id": f"jobindex-acme-{i}", "title": title,
            "company": "Acme", "location": "Copenhagen", "url": f"https://x/{i}",
            "description": "Requirements: experience required.",
            "source": "jobindex", "scraped_at": "2026-06-13T00:00:00Z",
        }
        for i, title in enumerate(["Data Scientist", "Warehouse Worker"])
    ]
    monkeypatch.setattr(ji, "scrape", lambda config, **kwargs: postings)
    monkeypatch.delattr(ji, "iter_scrape", raising=False)

    result = scrape_and_pass(profile_dir, jobs_dir, ["jobindex"])

    assert result["prescreen"]["scored"] == 2
    assert result["prescreen"]["kept"] == 1
    assert len(result["surviving_paths"]) == 1


def test_display_path_is_relative_to_the_repo_inside_it_and_whole_outside(tmp_path, monkeypatch):
    from door.commands import _common as common
    from door.core import workspace

    monkeypatch.setattr(workspace, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(workspace, "HOME", tmp_path / "repo")
    monkeypatch.chdir(tmp_path)

    assert common._display_path(tmp_path / "repo" / "jobs" / "output" / "a" / "cv.pdf") == "jobs/output/a/cv.pdf"
    assert common._display_path(tmp_path / "elsewhere" / "x.tar.gz") == str(tmp_path / "elsewhere" / "x.tar.gz")


def test_display_path_with_a_custom_home_is_relative_to_it_then_to_the_repo(tmp_path, monkeypatch):
    from door.commands import _common as common
    from door.core import workspace

    monkeypatch.setattr(workspace, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(workspace, "HOME", tmp_path / "home")

    assert common._display_path(tmp_path / "home" / "jobs" / "output" / "a" / "cv.pdf") == "jobs/output/a/cv.pdf"
    assert common._display_path(tmp_path / "repo" / "docs" / "x.md") == "docs/x.md"
    assert common._display_path(tmp_path / "other" / "x") == str(tmp_path / "other" / "x")


def test_cv_path_resolves_a_relative_cv_against_the_home(tmp_path, monkeypatch):
    from door.commands import _common as common
    from door.core import workspace

    monkeypatch.setattr(workspace, "HOME", tmp_path / "home")
    assert workspace.cv_path({"cv_content": "profile/cv.md"}, tmp_path) == tmp_path / "home" / "profile" / "cv.md"
    assert workspace.cv_path({"cv_content": str(tmp_path / "x.md")}, tmp_path) == tmp_path / "x.md"
