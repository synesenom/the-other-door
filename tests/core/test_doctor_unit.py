"""Unit tests for `door.core.doctor` (issue #138).

Every check is a pure function over injectable probes (`which`, paths,
`now`), so both outcomes are exercised without touching the real machine.
"""

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from door.core import doctor, workspace
from profile_utils import write_config

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def _which(*present):
    table = {name: f"/usr/bin/{name}" for name in present}
    return lambda name: table.get(name)


_NO_PROBE = lambda *a, **k: None  # noqa: E731 - keeps run_checks offline


def _statuses(checks):
    return {c["name"]: c["status"] for c in checks}


# --------------------------------------------------------------------------- #
# individual checks
# --------------------------------------------------------------------------- #

def test_check_python():
    assert doctor.check_python((3, 12, 4))["status"] == "ok"
    bad = doctor.check_python((3, 11, 9))
    assert bad["status"] == "missing" and bad["required"] is True
    assert "3.12" in bad["fix"]


def test_check_latex_falls_back_to_xelatex(tmp_path):
    check = doctor.check_latex(which=_which("xelatex"), home=tmp_path)
    assert check["status"] == "ok"
    assert "xelatex" in check["detail"]


def test_check_latex_missing_points_at_doctor_fix(tmp_path):
    check = doctor.check_latex(which=_which(), home=tmp_path)
    assert check["status"] == "missing" and check["required"] is True
    assert check["fix"] == "./door doctor --fix   (installs Tectonic, no sudo)"


def test_check_latex_finds_tectonic_in_local_bin_off_path(tmp_path):
    binary = tmp_path / ".local" / "bin" / "tectonic"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    check = doctor.check_latex(which=_which(), home=tmp_path)
    assert check["status"] == "ok"
    assert str(binary) in check["detail"]


def test_check_claude_cli():
    assert doctor.check_claude_cli(which=_which("claude"))["status"] == "ok"
    missing = doctor.check_claude_cli(which=_which(), home=Path("/nonexistent-home"))
    assert missing["status"] == "missing" and missing["required"] is True
    assert "npm" not in missing["fix"]


def test_check_claude_cli_details_carry_the_path():
    found = doctor.check_claude_cli(which=_which("claude"))
    assert found["details"] == {"path": "/usr/bin/claude"} and "/usr/bin/claude" in found["detail"]
    missing = doctor.check_claude_cli(which=_which(), home=Path("/nonexistent-home"))
    assert "path" not in (missing.get("details") or {})


def test_check_dev_deps(monkeypatch):
    assert doctor.check_dev_deps(find_spec=lambda name: object())["status"] == "ok"
    missing = doctor.check_dev_deps(find_spec=lambda name: None if name == "responses" else object())
    assert missing["status"] == "warn"
    assert "responses" in missing["detail"]
    assert missing["fix"] == "poetry install"


def test_check_profile(tmp_path):
    missing = doctor.check_profile(tmp_path / "profile")
    assert missing["status"] == "missing" and "init" in missing["fix"]

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    write_config(profile_dir, {"role_targets": ["x"], "location": "Copenhagen"})
    assert doctor.check_profile(profile_dir)["status"] == "ok"

    (profile_dir / "config.json").write_text(json.dumps({"remote": "sometimes", "min_sore": 0.5}))
    invalid = doctor.check_profile(profile_dir)
    assert invalid["status"] == "missing"
    assert "remote" in invalid["detail"] and "min_sore" in invalid["detail"]  # every error, not just the first
    assert "profile/config.json" in invalid["fix"]


def test_check_profile_reports_a_broken_employer_list(tmp_path):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    write_config(profile_dir, {"role_targets": ["x"], "location": "Copenhagen"})
    (profile_dir / "companies.json").write_text("{nope")
    broken = doctor.check_profile(profile_dir)
    assert broken["status"] == "missing" and "companies.json" in broken["detail"]
    assert "profile/companies.json" in broken["fix"]


# --------------------------------------------------------------------------- #
# run / scrape state (informational)
# --------------------------------------------------------------------------- #

def test_last_scrape_per_site(tmp_path, monkeypatch):
    from door.core import sites

    monkeypatch.setattr(sites, "boards_for_location", lambda location: ["jobindex", "thehub"])
    (tmp_path / "scrape_state.json").write_text(
        json.dumps({"jobindex": {"last_success": (NOW - timedelta(hours=5)).isoformat()}})
    )
    rows = doctor.last_scrape_per_site({"location": "Copenhagen"}, tmp_path, now=NOW)
    assert rows == [
        {"site": "jobindex", "last_success": (NOW - timedelta(hours=5)).isoformat(), "age_hours": 5.0},
        {"site": "thehub", "last_success": None, "age_hours": None},
    ]


def _auth(stdout="", returncode=0, exc=None, stderr=""):
    """A fake `subprocess.run` for `claude auth status --json`; records the argv."""
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if exc is not None:
            raise exc
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)

    run.calls = calls
    return run


def test_check_claude_login_ok_when_logged_in():
    run = _auth(json.dumps({"loggedIn": True, "authMethod": "oauth_token"}))
    check = doctor.check_claude_login("/usr/bin/claude", run=run)
    assert check["name"] == "claude login" and check["status"] == "ok"
    assert run.calls == [["/usr/bin/claude", "auth", "status", "--json"]]


def test_check_claude_login_missing_when_logged_out():
    check = doctor.check_claude_login("/usr/bin/claude", run=_auth(json.dumps({"loggedIn": False})))
    assert check["status"] == "missing" and check["required"] is True
    assert "claude auth login" in check["fix"]


def test_check_claude_login_rejects_an_api_key_login():
    """door runs on a Pro/Max plan only; an API key would bill per token."""
    run = _auth(json.dumps({"loggedIn": True, "authMethod": "api_key"}))
    check = doctor.check_claude_login("/usr/bin/claude", run=run)
    assert check["status"] == "missing"
    assert "Pro/Max" in check["detail"]


@pytest.mark.parametrize("run", [
    _auth("Unknown command: auth", returncode=1),
    _auth("not json"),
    _auth(exc=subprocess.TimeoutExpired("claude", 15)),
])
def test_check_claude_login_warns_when_it_cannot_tell(run):
    check = doctor.check_claude_login("/usr/bin/claude", run=run)
    assert check["status"] == "warn" and check["required"] is False


@pytest.mark.parametrize("run, said", [
    (_auth("", returncode=1, stderr="'C:\\x\\python.exe' is not recognized as an internal or external command"), "is not recognized"),
    (_auth(exc=OSError("[WinError 2] The system cannot find the file specified")), "WinError 2"),
    (_auth(exc=subprocess.TimeoutExpired("claude", 15)), "15"),
])
def test_check_claude_login_says_why_it_cannot_tell(run, said):
    """What claude said (or why it could not be run) is in the detail: on a user's computer it is the only clue."""
    assert said in doctor.check_claude_login("/usr/bin/claude", run=run)["detail"]


def test_check_claude_login_skipped_without_the_cli():
    assert doctor.check_claude_login(None, run=_auth()) is None


# --------------------------------------------------------------------------- #
# run_checks: aggregate
# --------------------------------------------------------------------------- #

def test_run_checks_ok_iff_every_required_check_passes(tmp_path):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    write_config(profile_dir, {"role_targets": ["x"], "location": "Copenhagen",
                               "linkedin_discovery": False})

    result = doctor.run_checks(
        profile_dir,
        tmp_path / "jobs",
        which=_which("xelatex", "claude"),
        find_spec=lambda name: object(),
        now=NOW,
        run=_auth(json.dumps({"loggedIn": True, "authMethod": "oauth_token"})),
        probe=_NO_PROBE,
    )
    statuses = _statuses(result["checks"])
    assert statuses["python"] == "ok"
    assert statuses["profile"] == "ok"
    assert statuses["latex"] == "ok"
    assert statuses["claude CLI"] == "ok"
    assert statuses["claude login"] == "ok"
    assert "playwright chromium" not in statuses  # no board and no discovery drives a browser
    assert not [c for c in result["checks"] if "login:" in c["name"] or "chrome" in c["name"].lower().split()]
    assert result["ok"] is True
    assert result["last_run"] is None
    assert result["last_scrape"] == [{"site": "jobindex", "last_success": None, "age_hours": None}]

    result = doctor.run_checks(
        profile_dir, tmp_path / "jobs", which=_which("xelatex"),
        find_spec=lambda name: object(), now=NOW, run=_auth(),
        probe=_NO_PROBE,
    )
    assert result["ok"] is False
    assert [c["name"] for c in result["checks"] if c["status"] == "missing"] == ["claude CLI"]
    assert "claude login" not in _statuses(result["checks"])

    result = doctor.run_checks(
        profile_dir, tmp_path / "jobs", which=_which("xelatex", "claude"),
        find_spec=lambda name: object(), now=NOW,
        run=_auth(json.dumps({"loggedIn": False})),
        probe=_NO_PROBE,
    )
    assert result["ok"] is False
    assert [c["name"] for c in result["checks"] if c["status"] == "missing"] == ["claude login"]


# --------------------------------------------------------------------------- #
# scraper probes (issue #178)
# --------------------------------------------------------------------------- #

def _write_run(runs_dir, name, sites):
    runs_dir.mkdir(parents=True, exist_ok=True)
    record = {"search": {"sites": [{"site": s, "count": c, "outcome": o} for s, c, o in sites]}}
    (runs_dir / f"{name}.json").write_text(json.dumps(record), encoding="utf-8")


def test_run_history_averages_ok_counts_per_site(tmp_path):
    runs = tmp_path / "runs"
    _write_run(runs, "2026-09-01", [("jobindex", 10, "ok"), ("thehub", 4, "ok")])
    _write_run(runs, "2026-09-02", [("jobindex", 20, "ok"), ("thehub", 0, "failed")])
    assert doctor.run_history(tmp_path) == {"jobindex": 15.0, "thehub": 4.0}


def test_run_history_uses_only_the_last_n_runs(tmp_path):
    runs = tmp_path / "runs"
    for i in range(doctor.HISTORY_RUNS):
        _write_run(runs, f"2026-09-{i + 10:02d}", [("jobindex", 10, "ok")])
    _write_run(runs, "2026-01-01", [("jobindex", 1000, "ok")])  # oldest: outside the window
    assert doctor.run_history(tmp_path) == {"jobindex": 10.0}


def test_run_history_tolerates_missing_and_malformed(tmp_path):
    assert doctor.run_history(tmp_path) == {}
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "a.json").write_text("{not json", encoding="utf-8")
    (runs / "b.json").write_text(json.dumps({"started_at": "x"}), encoding="utf-8")
    assert doctor.run_history(tmp_path) == {}


def _result(**kw):
    base = {"raw": "<html/>", "ext": "html", "postings": [{"id": "1"}], "structure_ok": True}
    base.update(kw)
    return base


def test_assess_probe_drift_when_structure_is_broken():
    status, detail = doctor.assess_probe(_result(structure_ok=False, postings=[], reason="no results block"), 10)
    assert status == "drift" and "no results block" in detail


@pytest.mark.parametrize("flag", ["wall", "unreachable"])
def test_assess_probe_wall_or_unreachable_is_warn_never_drift(flag):
    status, _ = doctor.assess_probe(_result(structure_ok=False, postings=[], **{flag: True}), 10)
    assert status == "warn"


def test_assess_probe_zero_results_where_history_is_healthy():
    status, detail = doctor.assess_probe(_result(postings=[]), doctor.MIN_AVG_FOR_ZERO_WARN)
    assert status == "warn" and "0 results" in detail


@pytest.mark.parametrize("avg", [None, doctor.MIN_AVG_FOR_ZERO_WARN - 1])
def test_assess_probe_zero_results_without_healthy_history_is_ok(avg):
    assert doctor.assess_probe(_result(postings=[]), avg)[0] == "ok"


def test_assess_probe_unusually_many_results_is_warn():
    many = [{"id": str(i)} for i in range(6 * 2 + 1)]
    assert doctor.assess_probe(_result(postings=many), 2)[0] == "warn"
    assert doctor.assess_probe(_result(postings=many[:5]), 2)[0] == "ok"
    assert doctor.assess_probe(_result(postings=many), None)[0] == "ok"


def _stub(result):
    calls = []

    def probe(site, config, profile_dir):
        calls.append(site)
        return result(site) if callable(result) else result

    probe.calls = calls
    return probe


def _scraper_checks(tmp_path, config, probe, **kw):
    return doctor.check_scrapers(config, tmp_path / "profile", tmp_path / "jobs", probe=probe, now=NOW, **kw)


def test_check_scrapers_one_check_per_site_and_none_is_omitted(tmp_path, monkeypatch):
    from door.core import sites

    monkeypatch.setattr(sites, "boards_for_location", lambda location: ["jobindex", "thehub"])
    probe = _stub(lambda site: None if site == "thehub" else _result())
    checks = _scraper_checks(tmp_path, {"lever_companies": ["acme"]}, probe)
    assert [c["name"] for c in checks] == ["scraper: jobindex", "scraper: lever"]
    assert all(c["status"] == "ok" and c["required"] is False for c in checks)
    assert not (tmp_path / "jobs").exists()
    # the site in words, for the desktop app's list
    assert [c["details"] for c in checks] == [{"site": "jobindex", "site_name": sites.source_name("jobindex")}, {"site": "lever", "site_name": sites.source_name("lever")}]


def test_check_scrapers_drift_saves_raw_response(tmp_path):
    probe = _stub(_result(structure_ok=False, postings=[], raw="<html>new</html>", reason="no block"))
    [check] = _scraper_checks(tmp_path, {}, probe)
    assert check["status"] == "drift" and check["fixable"] is True
    saved = tmp_path / "jobs" / "drift" / "jobindex" / "20260924T120000Z.html"
    assert saved.read_text(encoding="utf-8") == "<html>new</html>"
    assert str(saved) in check["detail"]


def test_check_scrapers_warn_saves_raw_but_wall_is_not_fixable(tmp_path, monkeypatch):
    from door.core import sites

    monkeypatch.setattr(sites, "boards_for_location", lambda location: [])
    probe = _stub(_result(structure_ok=False, postings=[], wall=True, ext="json", raw="{}"))
    [check] = _scraper_checks(tmp_path, {"lever_companies": ["acme"]}, probe)
    assert check["status"] == "warn" and check["fixable"] is False
    assert (tmp_path / "jobs" / "drift" / "lever" / "20260924T120000Z.json").exists()


def test_check_scrapers_plausibility_warn_is_fixable(tmp_path):
    runs = tmp_path / "jobs" / "runs"
    _write_run(runs, "r1", [("jobindex", 30, "ok")])
    [check] = _scraper_checks(tmp_path, {}, _stub(_result(postings=[])))
    assert check["status"] == "warn" and check["fixable"] is True


def test_check_scrapers_probe_exception_is_unreachable_warn(tmp_path):
    def boom(site, config, profile_dir):
        raise RuntimeError("kaboom")

    [check] = _scraper_checks(tmp_path, {}, boom)
    assert check["status"] == "warn" and check["fixable"] is False
    assert "unreachable" in check["detail"] and "Traceback" not in check["detail"]


def test_default_probe_returns_none_without_probe_function(monkeypatch):
    import sys
    import types

    from door.core.sites import SITES, Site

    monkeypatch.setitem(SITES, "fakesite", Site("fakesite", label="Fake site", terms_url="https://example.com/terms", verdict="allowed", terms_summary="x"))
    monkeypatch.setitem(sys.modules, SITES["fakesite"].module, types.ModuleType("fakesite"))
    assert doctor.default_probe("fakesite", {}, Path(".")) is None


def test_run_checks_scraper_checks_come_last_and_are_non_fatal(tmp_path):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    write_config(profile_dir, {"role_targets": ["x"], "location": "Copenhagen"})
    kw = dict( find_spec=lambda n: object(), now=NOW, run=_auth(json.dumps({"loggedIn": True, "authMethod": "oauth_token"})),
              probe=_stub(_result(structure_ok=False, postings=[], reason="x")), probe_sites=True)
    result = doctor.run_checks(profile_dir, tmp_path / "jobs", which=_which("xelatex", "claude"), **kw)
    names = [c["name"] for c in result["checks"]]
    assert names[-1] == "scraper: jobindex"
    assert result["checks"][-1]["status"] == "drift"
    assert result["ok"] is True
    result = doctor.run_checks(profile_dir, tmp_path / "jobs", which=_which("xelatex"), **kw)
    assert result["ok"] is False


# --------------------------------------------------------------------------- #
# browser requirement, opt-in probes, the MCP server entry
# --------------------------------------------------------------------------- #

def _checks_for(tmp_path, **kw):
    from profile_utils import write_config

    profile_dir = tmp_path / "profile"
    write_config(profile_dir, kw.pop("config", {}))
    return doctor.run_checks(
        profile_dir, tmp_path / "jobs", which=_which("xelatex", "claude"),
        find_spec=lambda name: object(), now=NOW,
        run=_auth(json.dumps({"loggedIn": True, "authMethod": "oauth_token"})), repo_root=tmp_path, **kw,
    )


def test_run_checks_probes_only_when_asked(tmp_path):
    calls = []

    def probe(site, config, profile_dir):
        calls.append(site)
        return _result()

    quiet = _checks_for(tmp_path, probe=probe)
    assert calls == [] and not [c for c in quiet["checks"] if c["name"].startswith("scraper: ")]
    probed = _checks_for(tmp_path, probe=probe, probe_sites=True)
    assert calls == ["jobindex"] and [c["name"] for c in probed["checks"] if c["name"].startswith("scraper: ")] == ["scraper: jobindex"]


def test_probes_get_the_followed_employers_of_their_platform(tmp_path):
    """A feed scraper's probe reads its employers; they live in profile/companies.json."""
    from door.core import companies

    profile_dir = tmp_path / "profile"
    seen = {}

    def probe(site, config, profile_dir):
        seen.update(config)
        return _result()

    (tmp_path / "profile").mkdir(exist_ok=True)
    companies.save(profile_dir, [companies.Company(
        name="Stripe", feed=companies.Feed(platform="greenhouse", id="stripe"), status="followed", found_via="manual")])
    _checks_for(tmp_path, probe=probe, probe_sites=True)

    assert seen["greenhouse_boards"] == ["stripe"]


def _mcp_json(root: Path, command: str, env: dict | None = None) -> None:
    entry = {"command": command, "args": ["-m", "door.mcp_server"], "env": {"PYTHONPATH": "src"} if env is None else env}
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"door": entry}}))


def test_check_mcp_server_ok_when_the_venv_interpreter_exists(tmp_path):
    _mcp_json(tmp_path, ".venv/bin/python")
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("")
    check = doctor.check_mcp_server(tmp_path, find_spec=lambda name: object(), platform="linux")
    assert check["status"] == "ok" and check["required"] is False


def test_check_mcp_server_warns_when_the_venv_is_missing(tmp_path):
    """`poetry install` never ran: Claude Code would report the server as failed to connect."""
    _mcp_json(tmp_path, ".venv/bin/python")
    check = doctor.check_mcp_server(tmp_path, find_spec=lambda name: object(), platform="linux")
    assert check["status"] == "warn"
    assert check["fix"] == "poetry install"


def test_check_mcp_server_names_the_windows_interpreter(tmp_path):
    _mcp_json(tmp_path, ".venv/bin/python")
    check = doctor.check_mcp_server(tmp_path, find_spec=lambda name: object(), platform="win32")
    assert check["status"] == "warn"
    assert "Scripts" in check["fix"] and "python.exe" in check["fix"]


def test_check_mcp_server_warns_when_the_mcp_package_is_missing(tmp_path):
    _mcp_json(tmp_path, ".venv/bin/python")
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("")
    check = doctor.check_mcp_server(tmp_path, find_spec=lambda name: None, platform="linux")
    assert check["status"] == "warn" and check["fix"] == "poetry install"


def test_check_mcp_server_warns_when_src_is_not_on_the_pythonpath(tmp_path):
    """The package lives in src/door/ and is never installed: without src on
    PYTHONPATH, `-m door.mcp_server` dies on import."""
    _mcp_json(tmp_path, ".venv/bin/python", env={})
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("")
    check = doctor.check_mcp_server(tmp_path, find_spec=lambda name: object(), platform="linux")
    assert check["status"] == "warn"
    assert "src" in check["detail"] and check["fix"] == "git checkout .mcp.json"


def test_mcp_server_env_resolves_a_relative_pythonpath_against_the_repo(tmp_path):
    _mcp_json(tmp_path, ".venv/bin/python", env={"PYTHONPATH": "src", "OTHER": "x"})
    assert doctor.mcp_server_env(tmp_path) == {"PYTHONPATH": str(tmp_path / "src"), "OTHER": "x"}


def test_mcp_server_env_is_empty_without_a_readable_entry(tmp_path):
    assert doctor.mcp_server_env(tmp_path) == {}


def test_check_mcp_server_with_a_bare_command_checks_path(tmp_path, monkeypatch):
    _mcp_json(tmp_path, "poetry")
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    check = doctor.check_mcp_server(tmp_path, find_spec=lambda name: object(), platform="linux")
    assert check["status"] == "warn" and "not on PATH" in check["detail"]


def test_mcp_json_points_at_the_in_project_interpreter():
    """The committed entry must not need Poetry on PATH (GUI-launched apps rarely have it)."""
    from paths import REPO_ROOT

    entry = json.loads((REPO_ROOT / ".mcp.json").read_text())["mcpServers"]["door"]
    assert entry["command"] == ".venv/bin/python"
    assert entry["env"]["PYTHONPATH"] == "src"  # the package is src/door/, never installed


# --------------------------------------------------------------------------- #
# probe_mcp_server: the live handshake `setup` ends with
# --------------------------------------------------------------------------- #

def _fake_run(stdout="", returncode=0, exc=None):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if exc is not None:
            raise exc
        return subprocess.CompletedProcess(argv, returncode, stdout, "boom")

    run.calls = calls
    return run


def test_probe_mcp_server_ok_when_the_server_answers_initialize(tmp_path):
    _mcp_json(tmp_path, ".venv/bin/python")
    run = _fake_run('{"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"door"}}}\n')
    check = doctor.probe_mcp_server(tmp_path, run=run, platform="linux")
    assert check["status"] == "ok"
    argv, kwargs = run.calls[0]
    assert argv == [str(tmp_path / ".venv" / "bin" / "python"), "-m", "door.mcp_server"]
    assert '"initialize"' in kwargs["input"] and kwargs["cwd"] == tmp_path and kwargs["timeout"]
    assert kwargs["env"]["PYTHONPATH"] == str(tmp_path / "src")
    assert kwargs["env"]["PATH"] == os.environ["PATH"]  # the rest of the environment is kept


@pytest.mark.parametrize("run", [
    _fake_run("", returncode=1),
    _fake_run('{"jsonrpc":"2.0","id":1,"error":{"message":"x"}}\n'),
    _fake_run(exc=subprocess.TimeoutExpired("python", 30)),
    _fake_run(exc=FileNotFoundError("python")),
])
def test_probe_mcp_server_missing_when_the_server_does_not_answer(tmp_path, run):
    _mcp_json(tmp_path, ".venv/bin/python")
    check = doctor.probe_mcp_server(tmp_path, run=run, platform="linux")
    assert check["status"] == "missing" and check["fix"]


def test_project_settings_pre_approve_the_mcp_server():
    """Without this, Claude Code asks before starting a .mcp.json server, and a "no" leaves /onboard without tools."""
    from paths import REPO_ROOT

    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text())
    assert "door" in settings["enabledMcpjsonServers"]


# --------------------------------------------------------------------------- #
# robots.txt verdicts and reserved sites (issue #226)
# --------------------------------------------------------------------------- #

@pytest.mark.usefixtures("obey_robots")
def test_check_scrapers_shows_the_robots_verdict(tmp_path):
    [check] = _scraper_checks(tmp_path, {}, _stub(_result(robots="allowed")))
    assert check["status"] == "ok" and check["detail"].endswith("robots.txt allows it")


@pytest.mark.usefixtures("obey_robots")
def test_a_robots_disallowed_probe_is_a_warning_nobody_can_fix_in_code(tmp_path):
    from door.scrapers import probe_failure
    from door.scrapers.http_client import RobotsBlocked

    result = probe_failure(RobotsBlocked("https://www.jobindex.dk/jobsoegning?q=x"), "html")
    [check] = _scraper_checks(tmp_path, {}, _stub(result))
    assert check["status"] == "warn" and check["fixable"] is False
    assert "robots.txt disallows it" in check["detail"]
    assert "--fix" not in check["fix"]


def test_a_reserved_site_is_never_probed(tmp_path, monkeypatch):
    from dataclasses import replace

    from door.core import sites

    monkeypatch.setitem(sites.SITES, "jobindex", replace(sites.SITES["jobindex"], verdict="reserved"))
    probe = _stub(_result())
    [check] = _scraper_checks(tmp_path, {}, probe)
    assert probe.calls == []
    assert check["status"] == "warn" and "reserved by its terms" in check["detail"]


def _terms_check(tmp_path, config):
    checks = _checks_for(tmp_path, config=config)["checks"]
    return next(c for c in checks if c["name"] == "terms: unsure sources on")


def test_doctor_lists_unsure_sources_that_are_on(tmp_path):
    check = _terms_check(tmp_path, {"location": "Budapest", "linkedin_discovery": True, "profession_discovery": False})
    assert check["status"] == "ok" and "LinkedIn" in check["detail"] and "profession.hu" not in check["detail"]


def test_doctor_says_none_when_no_unsure_source_is_on(tmp_path):
    check = _terms_check(tmp_path, {"location": "Copenhagen", "linkedin_discovery": False})
    assert check["status"] == "ok" and check["detail"] == "none"


# --------------------------------------------------------------------------- #
# DOOR_HOME (#216)
# --------------------------------------------------------------------------- #

def _custom_home(tmp_path, monkeypatch):
    from door.core import workspace

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(workspace, "HOME", home)
    monkeypatch.setattr(workspace, "MCP_CONFIG", home / ".mcp.json")
    return home


def test_run_checks_reports_the_data_folder(tmp_path):
    from door.core import workspace

    result = doctor.run_checks(
        tmp_path / "profile", tmp_path / "jobs", which=_which(), find_spec=lambda n: object(), now=NOW,
        run=_auth(""), probe=_NO_PROBE,
    )
    assert result["home"] == str(workspace.HOME)


def test_the_mcp_check_validates_the_generated_entry_for_a_custom_home(tmp_path, monkeypatch):
    from door.core import workspace

    _custom_home(tmp_path, monkeypatch)
    result = doctor.run_checks(
        tmp_path / "profile", tmp_path / "jobs", which=_which(), find_spec=lambda n: object(), now=NOW,
        run=_auth(""), probe=_NO_PROBE,
    )
    mcp = {c["name"]: c for c in result["checks"]}["mcp server"]
    assert mcp["status"] == "ok"   # no .venv in the home, the running interpreter is what counts
    assert not (workspace.HOME / ".mcp.json").exists()   # doctor never writes


def test_the_generated_mcp_check_fails_without_the_package(tmp_path, monkeypatch):
    _custom_home(tmp_path, monkeypatch)
    check = doctor.check_generated_mcp(find_spec=lambda n: None)
    assert check["status"] != "ok" and "mcp" in check["detail"]


def test_fix_strings_name_the_data_folder_only_when_it_is_not_the_checkout(tmp_path, monkeypatch):
    from door.core import workspace

    broken = tmp_path / "profile"
    broken.mkdir()
    (broken / "config.json").write_text(json.dumps({"remote": "sometimes"}))
    assert doctor.check_profile(broken)["fix"] == "fix profile/config.json"

    home = _custom_home(tmp_path, monkeypatch)
    monkeypatch.setattr(workspace, "PROFILE_DIR", home / "profile")
    assert doctor.check_profile(broken)["fix"] == f"fix {broken / 'config.json'}"


_ACCOUNT = {
    "loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "email": "jane@example.com",
    "orgName": "Jane's Org", "subscriptionType": "pro", "orgId": "org-secret", "configDirectory": "/home/j/.claude",
}


def test_check_claude_login_details_are_the_allowlist():
    check = doctor.check_claude_login("/usr/bin/claude", run=_auth(json.dumps(_ACCOUNT)))
    assert check["status"] == "ok"
    assert check["details"] == {k: v for k, v in _ACCOUNT.items() if k != "orgId"}
    assert "orgId" not in check["details"]
    assert check["detail"].startswith("logged in (claude.ai")
    assert "jane@example.com" in check["detail"] and "pro" in check["detail"]


def test_check_claude_login_api_key_keeps_details():
    run = _auth(json.dumps({"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"}))
    check = doctor.check_claude_login("/usr/bin/claude", run=run)
    assert check["status"] == "missing" and check["details"]["authMethod"] == "api_key"


def test_check_claude_login_logged_out_has_details():
    check = doctor.check_claude_login("/usr/bin/claude", run=_auth(json.dumps({"loggedIn": False})))
    assert check["details"] == {"loggedIn": False}


def test_check_claude_login_logged_out_exits_nonzero_and_still_reads_as_logged_out():
    # A real `claude auth status --json` exits 1 when signed out, with the status JSON on stdout.
    out = json.dumps({"loggedIn": False, "authMethod": "none", "configDirectory": "/c"})
    check = doctor.check_claude_login("/usr/bin/claude", run=_auth(out, returncode=1))
    assert check["status"] == "missing"
    assert "not logged in" in check["detail"]
    assert check["details"] == {"loggedIn": False, "authMethod": "none", "configDirectory": "/c"}


def test_check_claude_login_names_the_config_dir_door_uses():
    # The app signs in to the plan The other door's own claude calls use: the folder from claude_cli.env(), signed in or not.
    env = {"CLAUDE_CONFIG_DIR": "/home/j/.claude-work"}
    signed_in = doctor.check_claude_login("/usr/bin/claude", run=_auth(json.dumps(_ACCOUNT)), env=env)
    signed_out = doctor.check_claude_login("/usr/bin/claude", run=_auth(json.dumps({"loggedIn": False}), returncode=1), env=env)
    assert signed_in["details"]["doorConfigDir"] == "/home/j/.claude-work"
    assert signed_out["details"]["doorConfigDir"] == "/home/j/.claude-work"


def test_check_claude_login_has_no_config_dir_when_door_sets_none():
    check = doctor.check_claude_login("/usr/bin/claude", run=_auth(json.dumps(_ACCOUNT)), env={"PATH": "/bin"})
    assert "doorConfigDir" not in check["details"]


@pytest.mark.parametrize("run", [_auth("not json"), _auth("x", returncode=1)])
def test_check_claude_login_unreadable_has_no_details(run):
    assert "details" not in doctor.check_claude_login("/usr/bin/claude", run=run)


def test_check_claude_cli_finds_local_bin_off_path(tmp_path):
    binary = tmp_path / ".local" / "bin" / "claude"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    check = doctor.check_claude_cli(which=_which(), home=tmp_path)
    assert check["status"] == "ok" and str(binary) in check["detail"]


def test_check_claude_cli_fix_is_doctor_fix(tmp_path):
    check = doctor.check_claude_cli(which=_which(), home=tmp_path)
    assert check["fix"] == "./door doctor --fix   (installs the claude CLI, no sudo)"


def test_check_claude_login_unreadable_fix_is_claude_update():
    check = doctor.check_claude_login("/usr/bin/claude", run=_auth("not json"))
    assert check["fix"] == "claude update (the CLI may be too old for auth status)"


def test_outside_a_checkout_there_is_no_developer_tools_check(tmp_path, monkeypatch):
    # A packaged app has no pytest to look for (#223).
    monkeypatch.setattr(workspace, "is_checkout", lambda: False)
    result = doctor.run_checks(tmp_path / "profile", tmp_path / "jobs", which=_which("xelatex", "claude"))
    assert "dev dependencies" not in [c["name"] for c in result["checks"]]
    monkeypatch.setattr(workspace, "is_checkout", lambda: True)
    result = doctor.run_checks(tmp_path / "profile", tmp_path / "jobs", which=_which("xelatex", "claude"))
    assert "dev dependencies" in [c["name"] for c in result["checks"]]


def test_serve_instances_check_names_each_home_its_reach_phones_and_sleep(tmp_path, monkeypatch):
    from door.core import instances, pairing

    assert doctor.check_serve_instances() is None  # no instance: no line
    anna = tmp_path / "anna"
    instances.register(anna, port=8765, name="Anna", claude_config_dir=None)
    pairing.redeem(anna, pairing.new_code(anna, "Pixel"))

    up = doctor.check_serve_instances(reach=lambda port: True, sleep_minutes=lambda: 0)
    assert up["status"] == "ok" and up["required"] is False
    assert "Anna" in up["detail"] and "8765" in up["detail"] and "1 phone" in up["detail"]

    down = doctor.check_serve_instances(reach=lambda port: False, sleep_minutes=lambda: 10)
    assert down["status"] == "warn"
    assert "not answering" in down["detail"] and "sleeps after 10 minutes" in down["detail"]
