"""`doctor` command/tool and the missing-tool guards (issue #138)."""

import json
import subprocess
import types

import pytest
from click.testing import CliRunner

from door.cli import cli
from door.commands import _common as common
from door.commands import compile as compile_cmd
from door.commands import prepare as prepare_cmd
from door.commands import setup as setup_cmd
from door.core import workspace
import door.core.doctor as doctor
import door.mcp_server as server
from profile_utils import write_config
from cli_utils import result_text


@pytest.fixture
def env(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    write_config(profile_dir, {"role_targets": ["x"], "location": "Copenhagen"})
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)
    return types.SimpleNamespace(profile_dir=profile_dir, jobs_dir=jobs_dir, tmp_path=tmp_path)


def _fake_checks(ok: bool):
    checks = [
        {"name": "python", "status": "ok", "required": True, "detail": "Python 3.12.3", "fix": None},
        {"name": "latex", "status": "ok" if ok else "missing", "required": True,
         "detail": "xelatex: /usr/bin/xelatex" if ok else "no xelatex on PATH",
         "fix": None if ok else "sudo apt-get install -y texlive-xetex"},
        {"name": "dev dependencies", "status": "warn", "required": False, "detail": "missing: pytest",
         "fix": "poetry install"},
    ]
    return {
        "ok": ok,
        "checks": checks,
        "last_run": {"started_at": "2026-09-24T07:00:00+00:00", "outcome": "failed", "failures": ["thehub"], "new_above_threshold": 3},
        "last_scrape": [{"site": "jobindex", "last_success": "2026-09-24T07:00:00+00:00", "age_hours": 5.0},
                        {"site": "thehub", "last_success": None, "age_hours": None}],
    }


def test_doctor_core_delegates_to_run_checks(env, monkeypatch):
    seen = {}

    def fake(profile_dir, jobs_dir, **kw):
        seen.update(profile_dir=profile_dir, jobs_dir=jobs_dir)
        return _fake_checks(True)

    monkeypatch.setattr(doctor, "run_checks", fake)
    assert setup_cmd._doctor_core()["ok"] is True
    assert seen == {"profile_dir": env.profile_dir, "jobs_dir": env.jobs_dir}


def test_doctor_command_exit_0_with_warnings(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", lambda *a, **k: _fake_checks(True))
    result = CliRunner().invoke(cli, ["doctor"])
    assert result.exit_code == 0, result_text(result)
    out = result.output
    assert "Prerequisites" in out
    assert "✓ python" in out and "Python 3.12.3" in out
    assert "⚠ dev dependencies" in out  # optional: a warning, never a failure
    assert "fix: poetry install" in out
    assert out.index("Prerequisites") < out.index("Last run") < out.index("Last scrape")
    assert "failed" in out and "thehub" in out
    assert "jobindex" in out and "never" in out
    assert "✓ All required prerequisites are in place." in out
    assert "\x1b[" not in out  # no colour codes into a pipe


def test_doctor_fix_line_sits_under_its_check(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", lambda *a, **k: _fake_checks(False))
    lines = CliRunner().invoke(cli, ["doctor"]).output.splitlines()
    at = next(i for i, line in enumerate(lines) if "✗ latex" in line)
    assert "fix: sudo apt-get install -y texlive-xetex" in lines[at + 1]
    assert lines[at + 1].index("fix:") > lines[at].index("✗")  # indented under the mark


def test_doctor_without_a_run_points_at_find(env, monkeypatch):
    report = _fake_checks(True)
    report.update(last_run=None, last_scrape=[])
    monkeypatch.setattr(doctor, "run_checks", lambda *a, **k: report)
    out = CliRunner().invoke(cli, ["doctor"]).output
    assert "none yet" in out and "./door find" in out
    assert "Last scrape" not in out


def test_doctor_keeps_markup_like_details_verbatim(env, monkeypatch):
    report = _fake_checks(True)
    report["checks"][0]["detail"] = "sites: [bold]x[/bold] is not a site"
    monkeypatch.setattr(doctor, "run_checks", lambda *a, **k: report)
    assert "[bold]x[/bold]" in CliRunner().invoke(cli, ["doctor"]).output


def test_doctor_prints_drift_checks_and_still_exits_0(env, monkeypatch):
    report = _fake_checks(True)
    report["checks"].append({
        "name": "scraper: jobindex", "status": "drift", "required": False,
        "detail": "no results block", "fix": "choose `fix scraper` in `setup`", "fixable": True,
    })
    report["checks"].append({
        "name": "scraper: thehub", "status": "warn", "required": False,
        "detail": "a login wall", "fix": "try later", "fixable": False,
    })
    report["checks"].append({"name": "scraper: jobnet", "status": "ok", "required": False, "detail": "12 postings", "fix": None})
    monkeypatch.setattr(doctor, "run_checks", lambda *a, **k: report)
    result = CliRunner().invoke(cli, ["doctor"])
    assert result.exit_code == 0, result_text(result)
    out = result.output
    assert out.index("Prerequisites") < out.index("Live probes") < out.index("Last run")
    probes = out[out.index("Live probes"):out.index("Last run")]
    assert "✗ jobindex" in probes and "no results block" in probes  # drift: the scraper no longer fits
    assert "⚠ thehub" in probes and "a login wall" in probes       # a wall or an unreachable site
    assert "✓ jobnet" in probes
    assert "fix: choose `fix scraper` in `setup`" in probes
    assert "scraper: jobindex" not in out[:out.index("Live probes")]


def test_doctor_probe_reports_progress_per_site(env, monkeypatch):
    """The core never prints, but a slow probe tells a reporter which site it is on."""
    from door.core import progress

    monkeypatch.setattr(doctor, "default_probe", lambda site, config, profile_dir: None)
    events = []

    class Collect:
        def report(self, event):
            events.append(event.message)

    with progress.activate(Collect()):
        setup_cmd._doctor_core(probe=True)
    assert any("jobindex" in m for m in events)


def test_doctor_does_not_probe_live_sites_by_default(env, monkeypatch):
    """The checks are instant and offline unless the probes are asked for."""
    called = []
    monkeypatch.setattr(doctor, "default_probe", lambda site, config, profile_dir: called.append(site))
    result = setup_cmd._doctor_core()
    assert called == []
    assert not [c for c in result["checks"] if c["name"].startswith("scraper: ")]


def test_doctor_probes_live_sites_when_asked(env, monkeypatch):
    """`--probe` / `probe=True` runs the default (real) probe per configured site."""
    called = []
    monkeypatch.setattr(doctor, "default_probe", lambda site, config, profile_dir: called.append(site))
    setup_cmd._doctor_core(probe=True)
    assert called == ["jobindex"]

    called.clear()
    result = CliRunner().invoke(cli, ["doctor", "--probe"])
    assert result.exit_code in (0, 1), result_text(result)
    assert called == ["jobindex"]

    called.clear()
    server.doctor(probe=True)
    assert called == ["jobindex"]


def test_doctor_command_exit_1_when_required_missing(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", lambda *a, **k: _fake_checks(False))
    result = CliRunner().invoke(cli, ["doctor"])
    assert result.exit_code == 1
    assert "✗ latex" in result.output
    assert "fix: sudo apt-get install -y texlive-xetex" in result.output
    assert "✗ Missing: latex." in result_text(result)
    assert "All required prerequisites" not in result_text(result)


def test_doctor_real_checks_run_offline(env, monkeypatch):
    """No fakes: the real checks must complete without network or side effects."""
    monkeypatch.setattr(doctor, "default_probe", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    result = setup_cmd._doctor_core()
    names = {c["name"] for c in result["checks"]}
    assert {"python", "profile", "latex", "claude CLI", "mcp server"} <= names


# --------------------------------------------------------------------------- #
# guards
# --------------------------------------------------------------------------- #

def test_compile_without_tex_is_a_one_line_error_from_the_tool(env, monkeypatch):
    out = env.jobs_dir / "output" / "jobindex-acme-ds"
    out.mkdir(parents=True)
    (out / "cv.tex").write_text("x")

    def no_tex(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(subprocess, "run", no_tex)
    with pytest.raises(common.MissingToolError, match="no LaTeX compiler"):
        compile_cmd._compile_core("jobindex-acme-ds", jobs_dir=env.jobs_dir)

    monkeypatch.setattr(workspace, "JOBS_DIR", env.jobs_dir)
    error = server.compile("jobindex-acme-ds")["error"]
    assert "no LaTeX compiler" in error
    assert "door doctor --fix" in error
    assert "None" not in error  # the hint must not depend on what this machine has installed


def _posting(env, job_id="jobindex-acme-ds"):
    from datetime import datetime, timezone

    site_dir = env.jobs_dir / datetime.now(timezone.utc).strftime("%Y-%m-%d") / "jobindex"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / f"{job_id}.json").write_text(json.dumps({
        "id": job_id, "title": "DS", "company": "Acme", "location": "Cph", "url": "u",
        "description": "d", "source": "jobindex", "score": 0.9,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }))


def test_prepare_without_claude_fails_before_tailoring(env, monkeypatch):
    _posting(env)
    monkeypatch.setattr(common, "_claude_available", lambda: False)
    monkeypatch.setattr(prepare_cmd, "_run_tailor", lambda *a, **k: pytest.fail("tailored without claude"))

    result = prepare_cmd._prepare_core("jobindex-acme-ds", jobs_dir=env.jobs_dir)
    assert result["outcome"] == "failed"
    assert "./door doctor --fix" in result["error"] and "npm" not in result["error"]

    out = CliRunner().invoke(cli, ["jobs", "prepare", "jobindex-acme-ds"])
    assert out.exit_code == 1
    assert "claude" in result_text(out)


def test_prepare_top_match_without_claude_fails_before_selecting(env, monkeypatch):
    _posting(env)
    monkeypatch.setattr(common, "_claude_available", lambda: False)
    monkeypatch.setattr(prepare_cmd, "_top_match_id", lambda *a, **k: pytest.fail("selected a job without claude"))
    result = prepare_cmd._prepare_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)
    assert result["outcome"] == "failed"
    assert result["job_id"] is None
    assert "claude" in result["error"]


def test_doctor_prints_the_data_folder(env, monkeypatch):
    monkeypatch.setattr(workspace, "HOME", env.tmp_path / "home")
    monkeypatch.setattr(doctor, "run_checks", lambda *a, **k: _fake_checks(True))
    result = CliRunner().invoke(cli, ["doctor"])
    assert result.exit_code == 0, result_text(result)
    assert f"data folder: {env.tmp_path / 'home'}" in result.output


def test_mcp_registration_passes_door_home_only_when_it_is_not_the_checkout(tmp_path, monkeypatch):
    from door.core import installers

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".mcp.json").write_text(
        '{"mcpServers": {"door": {"command": ".venv/bin/python", "args": ["-m", "door.mcp_server"]}}}'
    )
    monkeypatch.setattr(workspace, "HOME", repo)
    monkeypatch.setattr(workspace, "REPO_ROOT", repo)
    default = installers.plan_mcp_registration(repo, "windows", which=lambda n: "C:/claude")["commands"][0]
    assert not any("DOOR_HOME" in a for a in default)

    monkeypatch.setattr(workspace, "HOME", tmp_path / "data")
    custom = installers.plan_mcp_registration(repo, "windows", which=lambda n: "C:/claude")["commands"][0]
    assert f"DOOR_HOME={tmp_path / 'data'}" in custom


# Captured at import, before the suite's autouse fixture stubs it to "claude present".
_REAL_CLAUDE_AVAILABLE = common._claude_available


def test_claude_available_follows_find_claude(monkeypatch):
    from door.core import installers

    monkeypatch.setattr(common, "_claude_available", _REAL_CLAUDE_AVAILABLE)
    monkeypatch.setattr(installers, "find_claude", lambda *a, **k: "/x/claude")
    assert common._claude_available() is True
    monkeypatch.setattr(installers, "find_claude", lambda *a, **k: None)
    assert common._claude_available() is False
