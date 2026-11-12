"""Unit tests for The other door's importable `_*_core` functions (issue #79).

These exercise the extracted core functions directly (no Click, no CliRunner)
so they can be reused by the MCP adapter as well as the CLI. Core functions
return structured data and raise ordinary exceptions instead of calling
`click.echo`/`sys.exit` — this is a hard requirement so that a stray print
never corrupts an MCP stdio JSON-RPC stream.
"""

import builtins
import json
import sys
import types
from datetime import date

import pytest

from door.commands import _common as common
from door.commands import compile as compile_cmd
from door.commands import scrape as scrape_cmd
from door.commands import status as status_cmd
import subprocess
from profile_utils import write_config
import door.core.tracker as tracker_mod


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


def _fake_history_store(monkeypatch, *, is_new=True):
    import door.core.history as hist_mod

    calls = {"touch": [], "record": [], "save": 0}

    class FakeStore:
        def __init__(self, path):
            calls["path"] = path

        def is_new(self, platform_id, source, recheck_after_days, **kw):
            return is_new

        def record(self, *args, **kw):
            calls["record"].append(args)

        def touch(self, platform_id, **kw):
            calls["touch"].append(platform_id)

        def known_ids(self, *args, **kw):
            return frozenset()

        def save(self):
            calls["save"] += 1

    monkeypatch.setattr(hist_mod, "HistoryStore", FakeStore)
    return calls


# --------------------------------------------------------------------------- #
# ALL_SITES
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# _set_status_core
# --------------------------------------------------------------------------- #

def test_set_status_core_happy_path_returns_dict_and_updates_ledger(tmp_path):
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()

    result = status_cmd._set_status_core("job-abc", "applied", jobs_dir=jobs_dir)

    assert {k: result[k] for k in ("job_id", "status", "notes")} == {"job_id": "job-abc", "status": "applied", "notes": None}

    ledger = tracker_mod.ApplicationTracker(jobs_dir / "applications.json")
    assert ledger.get_status("job-abc") == "applied"


def test_set_status_core_invalid_status_raises_value_error(tmp_path):
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()

    with pytest.raises(ValueError):
        status_cmd._set_status_core("job-abc", "hired", jobs_dir=jobs_dir)


def test_set_status_core_duplicate_application_raises(tmp_path):
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()

    status_cmd._set_status_core("job-abc", "applied", jobs_dir=jobs_dir)
    with pytest.raises(tracker_mod.DuplicateApplicationError):
        status_cmd._set_status_core("job-abc", "applied", jobs_dir=jobs_dir)


def test_set_status_core_invalid_job_id_raises_value_error(tmp_path):
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()

    with pytest.raises(ValueError):
        status_cmd._set_status_core("../evil", "applied", jobs_dir=jobs_dir)


# --------------------------------------------------------------------------- #
# _compile_core
# --------------------------------------------------------------------------- #

class _FakeCompleted:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


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


def test_compile_core_missing_tex_file_is_skipped_no_subprocess_call(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    out_dir = jobs_dir / "output" / "job1"
    out_dir.mkdir(parents=True)

    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: calls.append(a) or _FakeCompleted(0))

    result = compile_cmd._compile_core("job1", jobs_dir=jobs_dir)

    assert calls == []
    assert result["job_id"] == "job1"
    assert result["output_dir"] == str(out_dir)
    assert result["results"] == [
        {"file": "cv.tex", "status": "skipped"},
        {"file": "cover_letter.tex", "status": "skipped"},
    ]


def test_compile_core_xelatex_success(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    out_dir = jobs_dir / "output" / "job1"
    out_dir.mkdir(parents=True)
    (out_dir / "cv.tex").write_text(r"\documentclass{article}")

    calls = []
    monkeypatch.setattr(compile_cmd, "_find_tectonic", lambda: None)  # xelatex only: no Tectonic installed
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or _FakeCompleted(0),
    )

    result = compile_cmd._compile_core("job1", jobs_dir=jobs_dir)

    assert len(calls) == 1
    assert calls[0][0] == "xelatex"
    entry = result["results"][0]
    assert entry["status"] == "compiled"
    assert entry["compiler"] == "xelatex"
    assert entry["pdf"] == str(out_dir / "cv.pdf")


def test_compile_core_xelatex_failure_is_an_error_and_no_other_compiler_runs(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    out_dir = jobs_dir / "output" / "job1"
    out_dir.mkdir(parents=True)
    (out_dir / "cv.tex").write_text(r"\documentclass{article}")
    calls = []
    monkeypatch.setattr(compile_cmd, "_find_tectonic", lambda: None)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd[0]) or _FakeCompleted(1, stderr="xelatex broke"))

    entry = compile_cmd._compile_core("job1", jobs_dir=jobs_dir)["results"][0]

    assert calls == ["xelatex"]
    assert entry["status"] == "error" and entry["stderr"] == "xelatex broke"


def test_compile_core_no_compiler_names_tectonic_and_xelatex(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    out_dir = jobs_dir / "output" / "job1"
    out_dir.mkdir(parents=True)
    (out_dir / "cv.tex").write_text("x")
    monkeypatch.setattr(compile_cmd, "_find_tectonic", lambda: None)

    def missing(*a, **kw):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(common.MissingToolError) as err:
        compile_cmd._compile_core("job1", jobs_dir=jobs_dir)
    assert "pdflatex" not in str(err.value) and "xelatex" in str(err.value)


def test_compile_core_both_compilers_fail_reports_error(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    out_dir = jobs_dir / "output" / "job2"
    out_dir.mkdir(parents=True)
    (out_dir / "cv.tex").write_text("bad")

    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kw: _FakeCompleted(1, stderr="LaTeX error"),
    )

    result = compile_cmd._compile_core("job2", jobs_dir=jobs_dir)

    entry = result["results"][0]
    assert entry["status"] == "error"
    assert entry["stderr"] == "LaTeX error"


# --------------------------------------------------------------------------- #
# _render_pages / compile --render
# --------------------------------------------------------------------------- #

def _inject_fake_pdf_render(monkeypatch, fake_render):
    pdf_render_mod = types.ModuleType("door.tailoring.pdf_render")
    pdf_render_mod.render_pdf_pages = fake_render
    tailoring_pkg = types.ModuleType("tailoring")
    tailoring_pkg.pdf_render = pdf_render_mod
    monkeypatch.setitem(sys.modules, "tailoring", tailoring_pkg)
    monkeypatch.setitem(sys.modules, "door.tailoring.pdf_render", pdf_render_mod)


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


def test_compile_core_without_render_renders_nothing(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    out_dir = jobs_dir / "output" / "job1"
    out_dir.mkdir(parents=True)
    (out_dir / "cv.tex").write_text(r"\documentclass{article}")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _FakeCompleted(0))
    _inject_fake_pdf_render(monkeypatch, lambda pdf, out: pytest.fail("rendered without render=True"))

    assert "render" not in compile_cmd._compile_core("job1", jobs_dir=jobs_dir)


def test_compile_core_render_renders_only_the_pdfs_that_compiled(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    out_dir = jobs_dir / "output" / "job1"
    out_dir.mkdir(parents=True)
    (out_dir / "cv.tex").write_text(r"\documentclass{article}")
    (out_dir / "cover_letter.tex").write_text("bad")
    (out_dir / "cv.pdf").write_bytes(b"%PDF-stub")
    (out_dir / "cover_letter.pdf").write_bytes(b"%PDF-stale")
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kw: _FakeCompleted(1 if cmd[-1].endswith("cover_letter.tex") else 0, stderr="LaTeX error"),
    )
    rendered = []
    _inject_fake_pdf_render(monkeypatch, lambda pdf, out: rendered.append(pdf.name) or [out / f"{pdf.stem}_page_1.png"])

    result = compile_cmd._compile_core("job1", render=True, jobs_dir=jobs_dir)

    assert rendered == ["cv.pdf"]
    assert result["render"] == [
        {"file": "cv.pdf", "status": "rendered", "pages": [str(out_dir / "cv_page_1.png")], "page_count": 1}
    ]


# --------------------------------------------------------------------------- #
# _scrape_core
# --------------------------------------------------------------------------- #

def test_scrape_core_happy_path_writes_postings_and_returns_counts(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path)
    _fake_history_store(monkeypatch, is_new=True)

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
    # matching/prefilter and matching/dedup are implemented for real here.
    assert result["prefilter"]["available"] is True


def test_scrape_core_per_site_outcomes_preserved_in_order(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path, sites=("jobindex", "lever", "thehub"))
    write_config(profile_dir, {
        "role_targets": ["data scientist"],
        "location": "Copenhagen",
    })
    from door.core import companies as _companies
    _items = _companies.load(profile_dir)
    _companies.record(_items, "Acme", feed=("lever", "acme"), status="followed", found_via="manual", reason=None)
    _companies.save(profile_dir, _items)
    _fake_history_store(monkeypatch, is_new=True)

    import door.scrapers.boards.jobindex as ji
    posting = {
        "id": "jobindex-acme-x", "title": "X", "company": "Acme", "location": "CPH",
        "url": "u", "description": "We are looking for a data scientist who will join our team and work with Python.", "source": "jobindex", "scraped_at": "2026-06-13T00:00:00Z",
    }
    monkeypatch.setattr(ji, "scrape", lambda config, **kwargs: [posting])
    monkeypatch.delattr(ji, "iter_scrape", raising=False)

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "door.scrapers.feeds.lever":
            raise ImportError("simulated missing scraper")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    import door.scrapers.boards.thehub as th

    def boom(config, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(th, "scrape", boom)

    result = scrape_cmd._scrape_core(
        ["jobindex", "lever", "thehub"], jobs_dir=jobs_dir, profile_dir=profile_dir,
    )

    outcomes = [(entry["site"], entry["outcome"]) for entry in result["sites"]]
    assert outcomes == [("jobindex", "ok"), ("lever", "not_implemented"), ("thehub", "error")]
    assert result["sites"][2]["error"] == "kaboom"


def test_scrape_core_liveness_absent_is_none_and_not_called(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path)
    _fake_history_store(monkeypatch, is_new=True)

    import door.scrapers.boards.jobindex as ji
    monkeypatch.setattr(ji, "scrape", lambda config, **kwargs: [])
    monkeypatch.delattr(ji, "iter_scrape", raising=False)

    import door.core.liveness as liveness_mod

    def _should_not_be_called(paths, config):
        raise AssertionError("verify_liveness must NOT be called when flag is absent")

    monkeypatch.setattr(liveness_mod, "verify_liveness", _should_not_be_called)

    result = scrape_cmd._scrape_core(["jobindex"], jobs_dir=jobs_dir, profile_dir=profile_dir)

    assert result["liveness"] is None


def test_scrape_core_prefilter_unavailable_reports_false(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path)
    _fake_history_store(monkeypatch, is_new=True)

    import door.scrapers.boards.jobindex as ji
    monkeypatch.setattr(ji, "scrape", lambda config, **kwargs: [])
    monkeypatch.delattr(ji, "iter_scrape", raising=False)

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "door.matching.prefilter":
            raise ImportError("simulated missing module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    dedup_mod = types.ModuleType("door.matching.dedup")
    dedup_mod.dedup = lambda paths, config, aliases=None, earlier=None: paths
    monkeypatch.setitem(sys.modules, "door.matching.dedup", dedup_mod)

    result = scrape_cmd._scrape_core(["jobindex"], jobs_dir=jobs_dir, profile_dir=profile_dir)

    assert result["prefilter"] == {"available": False}
    assert result["surviving_paths"] == []


def test_scrape_core_dedup_unavailable_reports_false(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path)
    _fake_history_store(monkeypatch, is_new=True)

    import door.scrapers.boards.jobindex as ji
    monkeypatch.setattr(ji, "scrape", lambda config, **kwargs: [])
    monkeypatch.delattr(ji, "iter_scrape", raising=False)

    pf_mod = types.ModuleType("door.matching.prefilter")
    pf_mod.prefilter = lambda candidates_dir, config: ["a", "b"]
    monkeypatch.setitem(sys.modules, "door.matching.prefilter", pf_mod)

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "door.matching.dedup":
            raise ImportError("simulated missing module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    result = scrape_cmd._scrape_core(["jobindex"], jobs_dir=jobs_dir, profile_dir=profile_dir)

    assert result["prefilter"] == {"available": True, "survived": 2}
    assert result["dedup"] == {"available": False}


def test_scrape_core_surviving_paths_reflect_dedup_output(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path)
    _fake_history_store(monkeypatch, is_new=True)

    import door.scrapers.boards.jobindex as ji
    monkeypatch.setattr(ji, "scrape", lambda config, **kwargs: [])
    monkeypatch.delattr(ji, "iter_scrape", raising=False)

    pf_mod = types.ModuleType("door.matching.prefilter")
    pf_mod.prefilter = lambda candidates_dir, config: ["a", "b"]
    monkeypatch.setitem(sys.modules, "door.matching.prefilter", pf_mod)

    dedup_mod = types.ModuleType("door.matching.dedup")
    dedup_mod.dedup = lambda paths, config, aliases=None, earlier=None: paths[:1]
    monkeypatch.setitem(sys.modules, "door.matching.dedup", dedup_mod)

    # "a"/"b" are fake stand-in paths (no real files), so condense/prescreen
    # (which read the surviving JSON files from disk) are stubbed as no-ops
    # here — this test is only about the prefilter -> dedup wiring.
    condense_mod = types.ModuleType("door.matching.condense")
    condense_mod.condense_postings = lambda paths, terms, config: {"count": len(paths), "avg_ratio": None}
    condense_mod.extract_skill_terms = lambda cv_md, config: set()
    monkeypatch.setitem(sys.modules, "door.matching.condense", condense_mod)

    prescreen_mod = types.ModuleType("door.matching.prescreen")
    prescreen_mod.prescreen = lambda paths, config, terms: paths
    monkeypatch.setitem(sys.modules, "door.matching.prescreen", prescreen_mod)

    result = scrape_cmd._scrape_core(["jobindex"], jobs_dir=jobs_dir, profile_dir=profile_dir)

    assert result["prefilter"] == {"available": True, "survived": 2}
    assert result["dedup"] == {"available": True, "collapsed": 1, "remaining": 1}
    assert result["surviving_paths"] == ["a"]


def test_scrape_core_dedups_with_the_names_companies_json_holds_for_one_employer(tmp_path, monkeypatch):
    from door.core import companies as companies_store

    profile_dir, jobs_dir = _scrape_env(tmp_path)
    _fake_history_store(monkeypatch, is_new=True)
    companies_store.save(profile_dir, [
        companies_store.Company(name="Flugger", feed={"platform": "successfactors", "id": "jobs.flugger.com"},
                                status="followed", found_via="manual", aliases=["Flügger group A/S"]),
        companies_store.Company(name="Acme", feed={"platform": "greenhouse", "id": "acme"},
                                status="followed", found_via="manual"),
    ])

    import door.scrapers.boards.jobindex as ji
    monkeypatch.setattr(ji, "scrape", lambda config, **kwargs: [])
    monkeypatch.delattr(ji, "iter_scrape", raising=False)
    pf_mod = types.ModuleType("door.matching.prefilter")
    pf_mod.prefilter = lambda candidates_dir, config: []
    monkeypatch.setitem(sys.modules, "door.matching.prefilter", pf_mod)
    seen = {}
    dedup_mod = types.ModuleType("door.matching.dedup")
    dedup_mod.dedup = lambda paths, config, aliases=None, earlier=None: seen.setdefault("aliases", aliases) and paths
    monkeypatch.setitem(sys.modules, "door.matching.dedup", dedup_mod)

    scrape_cmd._scrape_core(["jobindex"], jobs_dir=jobs_dir, profile_dir=profile_dir)

    assert seen["aliases"] == [["Flugger", "Flügger group A/S"]]


# --------------------------------------------------------------------------- #
# _scrape_core — condense + prescreen (issue #143)
# --------------------------------------------------------------------------- #

def test_scrape_core_condense_and_prescreen_run_after_dedup(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path)
    _fake_history_store(monkeypatch, is_new=True)

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

    result = scrape_cmd._scrape_core(["jobindex"], jobs_dir=jobs_dir, profile_dir=profile_dir)

    assert result["condense"]["available"] is True
    assert result["condense"]["count"] == 1
    assert result["prescreen"]["available"] is True
    assert result["prescreen"]["scored"] == 1

    run_date = date.today().isoformat()
    out_file = jobs_dir / "postings" / run_date / "jobindex" / "jobindex-acme-data-scientist.json"
    data = json.loads(out_file.read_text())
    assert data["description_condensed"]
    assert "free lunch" not in data["description_condensed"].lower()
    assert "prescreen_score" in data


def test_scrape_core_condense_unavailable_reports_false(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path)
    _fake_history_store(monkeypatch, is_new=True)

    import door.scrapers.boards.jobindex as ji
    posting = {
        "id": "jobindex-acme-x", "title": "X", "company": "Acme", "location": "Copenhagen",
        "url": "u", "description": "We are looking for a data scientist who will join our team and work with Python.", "source": "jobindex", "scraped_at": "2026-06-13T00:00:00Z",
    }
    monkeypatch.setattr(ji, "scrape", lambda config, **kwargs: [posting])
    monkeypatch.delattr(ji, "iter_scrape", raising=False)

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "door.matching.condense":
            raise ImportError("simulated missing module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    result = scrape_cmd._scrape_core(["jobindex"], jobs_dir=jobs_dir, profile_dir=profile_dir)

    assert result["condense"] == {"available": False}
    # prescreen is an independent optional pass — it still runs even when
    # condense is unavailable (it just sees no description_condensed field).
    assert result["prescreen"]["available"] is True


def test_scrape_core_prescreen_unavailable_reports_false(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path)
    _fake_history_store(monkeypatch, is_new=True)

    import door.scrapers.boards.jobindex as ji
    posting = {
        "id": "jobindex-acme-x", "title": "X", "company": "Acme", "location": "Copenhagen",
        "url": "u", "description": "We are looking for a data scientist who will join our team and work with Python.", "source": "jobindex", "scraped_at": "2026-06-13T00:00:00Z",
    }
    monkeypatch.setattr(ji, "scrape", lambda config, **kwargs: [posting])
    monkeypatch.delattr(ji, "iter_scrape", raising=False)

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "door.matching.prescreen":
            raise ImportError("simulated missing module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    result = scrape_cmd._scrape_core(["jobindex"], jobs_dir=jobs_dir, profile_dir=profile_dir)

    assert result["condense"]["available"] is True
    assert result["prescreen"] == {"available": False}
    # surviving_paths still reflects condense's (pass-through) output.
    assert len(result["surviving_paths"]) == 1


def test_scrape_core_prescreen_honours_config_top_n(tmp_path, monkeypatch):
    profile_dir, jobs_dir = _scrape_env(tmp_path)
    write_config(profile_dir, {
        "role_targets": ["data scientist"],
        "location": "Copenhagen",
        "prescreen_top_n": 1,
        "prescreen_min": 0.0,
    })
    _fake_history_store(monkeypatch, is_new=True)

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

    result = scrape_cmd._scrape_core(["jobindex"], jobs_dir=jobs_dir, profile_dir=profile_dir)

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
    assert common._cv_path({"cv_content": "profile/cv.md"}, tmp_path) == tmp_path / "home" / "profile" / "cv.md"
    assert common._cv_path({"cv_content": str(tmp_path / "x.md")}, tmp_path) == tmp_path / "x.md"


def test_compile_core_refuses_a_tex_that_reads_a_file(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    out_dir = jobs_dir / "output" / "job1"
    out_dir.mkdir(parents=True)
    (out_dir / "cv.tex").write_text("\\documentclass{article}\\begin{document}\\input{/etc/passwd}\\end{document}")
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: calls.append(a) or _FakeCompleted(0))

    result = compile_cmd._compile_core("job1", jobs_dir=jobs_dir)

    assert calls == []  # never handed to LaTeX
    cv = result["results"][0]
    assert cv["status"] == "error" and "\\input" in cv["stderr"] and "refused" in cv["stderr"]


# --------------------------------------------------------------------------- #
# compile fills the ad's company and title in, escaped (#441)
# --------------------------------------------------------------------------- #

def _injected_posting():
    from paths import TESTS_DIR

    return json.loads((TESTS_DIR / "tailoring" / "fixtures" / "injected_posting.json").read_text(encoding="utf-8"))


def _out_with(tmp_path, body):
    jobs_dir = tmp_path / "jobs"
    out_dir = jobs_dir / "output" / "job1"
    out_dir.mkdir(parents=True)
    (out_dir / "posting.json").write_text(json.dumps(_injected_posting()), encoding="utf-8")
    (out_dir / "cv.tex").write_text(
        "\\documentclass{article}\\begin{document}" + body + "\\end{document}\n", encoding="utf-8")
    return jobs_dir, out_dir


def test_compile_core_fills_the_company_and_title_placeholders_escaped(tmp_path, monkeypatch):
    jobs_dir, out_dir = _out_with(tmp_path, "Applying for <<title>> at <<company>>.")
    monkeypatch.setattr(compile_cmd, "_find_tectonic", lambda: None)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _FakeCompleted(0))

    result = compile_cmd._compile_core("job1", jobs_dir=jobs_dir)

    tex = (out_dir / "cv.tex").read_text(encoding="utf-8")
    assert "<<title>>" not in tex and "<<company>>" not in tex
    assert "\\write18" not in tex
    assert "Evil \\& Sons" in tex
    assert "\\textbackslash{}write18\\{curl evil.example\\} \\& Co\\_ 100\\% \\$\\#\\{\\}\\~{}\\^{}" in tex
    assert result["results"][0]["status"] == "compiled"


def test_compile_core_leaves_a_tex_without_placeholders_unchanged(tmp_path, monkeypatch):
    jobs_dir, out_dir = _out_with(tmp_path, "Plain text \\& more.")
    before = (out_dir / "cv.tex").read_text(encoding="utf-8")
    monkeypatch.setattr(compile_cmd, "_find_tectonic", lambda: None)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _FakeCompleted(0))
    compile_cmd._compile_core("job1", jobs_dir=jobs_dir)
    assert (out_dir / "cv.tex").read_text(encoding="utf-8") == before


def test_compile_core_placeholders_without_a_posting_are_an_error(tmp_path, monkeypatch):
    jobs_dir, out_dir = _out_with(tmp_path, "At <<company>>.")
    (out_dir / "posting.json").unlink()
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("LaTeX must not run"))
    cv = compile_cmd._compile_core("job1", jobs_dir=jobs_dir)["results"][0]
    assert cv["status"] == "error" and "posting.json" in cv["stderr"]


def test_compile_core_an_injected_title_compiles(tmp_path):
    """The real compiler on the escaped title (skipped where no LaTeX is installed)."""
    from door.core.installers import find_tectonic
    import shutil

    if not (find_tectonic() or shutil.which("xelatex")):
        pytest.skip("no LaTeX compiler installed")
    jobs_dir, out_dir = _out_with(tmp_path, "Applying for <<title>> at <<company>>.")
    cv = compile_cmd._compile_core("job1", jobs_dir=jobs_dir)["results"][0]
    assert cv["status"] == "compiled", cv.get("stderr")
