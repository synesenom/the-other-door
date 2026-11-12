"""`door setup` / the `setup` tool (issue #141), and Tectonic support in
`compile` and `doctor`. Package-manager commands never execute: the doctor
checks and `subprocess.run` are faked and only the planned argv is asserted.
"""

import subprocess
import types

import pytest
from click.testing import CliRunner

from door.cli import cli
from door.commands import compile as compile_cmd
from door.commands import setup as setup_cmd
from door.core import workspace
import shutil
import door.core.doctor as doctor
import door.core.installers as installers
import door.mcp_server as server
from profile_utils import write_config
from cli_utils import result_text


def _check(name, status, required=True, fix=None):
    return {"name": name, "status": status, "required": required, "detail": f"{name} detail", "fix": fix}


def _report(*, latex="ok", claude="ok", profile="ok"):
    checks = [
        _check("python", "ok"),
        _check("profile", profile, fix="./door init"),
        _check("latex", latex, fix="apt-get install texlive-xetex"),
        _check("claude CLI", claude, fix="./door doctor --fix"),
    ]
    return {"ok": all(c["status"] != "missing" for c in checks), "checks": checks, "last_run": None, "last_scrape": []}


class Sequence:
    """run_checks returning a different report on each call (before / after install)."""

    def __init__(self, *reports):
        self.reports = list(reports)
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        return self.reports[min(self.calls, len(self.reports)) - 1]


@pytest.fixture
def env(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    write_config(profile_dir, {"role_targets": ["x"], "location": "Copenhagen"})
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)
    ran = []

    def fake_run(argv, **kwargs):
        ran.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(setup_cmd, "_detect_platform", lambda: "debian")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/curl" if name == "curl" else None)
    monkeypatch.setattr(compile_cmd, "_find_tectonic", lambda: None)
    real_plan = installers.plan_install

    def plan(tool, platform, **kw):  # keep the real ~/.local/bin out of these CLI tests
        if tool == "latex" and platform != "other":
            return {"tool": "latex", "commands": [LATEX_ARGV], "hint": None, "note": None}
        return real_plan(tool, platform, **kw)

    monkeypatch.setattr(installers, "plan_install", plan)
    monkeypatch.setattr(doctor, "probe_mcp_server", lambda *a, **k: _check("mcp server", "ok"))
    return types.SimpleNamespace(profile_dir=profile_dir, jobs_dir=jobs_dir, ran=ran)


LATEX_ARGV = ["sh", "-c", "<tectonic>"]  # see the `env` fixture: plan_install's latex step is stubbed
LATEX_ARGV_N = LATEX_ARGV
CLAUDE_ARGV = ["sh", "-c", "s=\"$(curl -fsSL https://claude.ai/install.sh)\" && printf '%s\\n' \"$s\" | bash -s stable"]


# --------------------------------------------------------------------------- #
# _setup_core
# --------------------------------------------------------------------------- #

def test_setup_core_without_yes_only_plans(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(latex="missing", claude="missing")))
    result = setup_cmd._setup_core()
    assert result["outcome"] == "needs_confirmation"
    assert result["platform"] == "debian"
    assert [(p["tool"], p["commands"]) for p in result["plan"]] == [
        ("latex", [LATEX_ARGV_N]),
        ("claude", [CLAUDE_ARGV]),
    ]
    assert env.ran == []


def test_setup_core_with_yes_runs_exactly_the_plan_and_rechecks(env, monkeypatch):
    checks = Sequence(_report(latex="missing", claude="missing"), _report())
    monkeypatch.setattr(doctor, "run_checks", checks)
    result = setup_cmd._setup_core(yes=True)
    assert env.ran == [LATEX_ARGV_N, CLAUDE_ARGV]
    assert result["outcome"] == "ok"
    assert [r["ok"] for r in result["results"]] == [True, True]
    assert checks.calls == 2
    assert result["doctor"]["ok"] is True


def test_setup_core_skips_satisfied_tools(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(claude="missing"), _report()))
    setup_cmd._setup_core(yes=True)
    assert env.ran == [CLAUDE_ARGV]


def test_setup_core_install_list_limits_the_steps(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(latex="missing", claude="missing")))
    result = setup_cmd._setup_core(install=["claude"], yes=True)
    assert env.ran == [CLAUDE_ARGV]
    assert result["outcome"] == "incomplete"  # latex still missing


def test_setup_core_unknown_tool(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report()))
    with pytest.raises(ValueError, match="unknown tool"):
        setup_cmd._setup_core(install=["emacs"])


def test_setup_core_without_curl_or_npm_runs_nothing_and_shows_the_hint(env, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(claude="missing")))
    result = setup_cmd._setup_core(install=["claude"], yes=True)
    assert env.ran == []
    claude_plan = [p for p in result["plan"] if p["tool"] == "claude"][0]
    assert "install curl" in claude_plan["hint"]


def test_setup_core_stops_a_tool_at_its_first_failing_command(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(claude="missing")))
    two = {"tool": "claude", "commands": [["one"], ["two"]], "hint": None, "note": None}
    real_plan = installers.plan_install
    monkeypatch.setattr(installers, "plan_install", lambda tool, platform, **kw: two if tool == "claude" else real_plan(tool, platform, **kw))

    def failing(argv, **kwargs):
        env.ran.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, "", "E: Unable to locate package")

    monkeypatch.setattr(subprocess, "run", failing)
    result = setup_cmd._setup_core(yes=True)
    assert [r for r in env.ran if r in (["one"], ["two"])] == [["one"]]
    assert "Unable to locate package" in [r for r in result["results"] if r["tool"] == "claude"][0]["error"]


def test_setup_core_missing_package_manager_is_a_result_not_a_crash(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(latex="missing")))

    def no_binary(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(subprocess, "run", no_binary)
    result = setup_cmd._setup_core(yes=True)
    assert result["results"][0]["ok"] is False
    assert "`sh` not found" in result["results"][0]["error"]


def test_setup_core_hint_when_no_route(env, monkeypatch):
    monkeypatch.setattr(setup_cmd, "_detect_platform", lambda: "other")
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(latex="missing")))
    plan = setup_cmd._setup_core()["plan"]
    assert plan[0]["commands"] == [] and "tectonic" in plan[0]["hint"].lower()


def test_setup_core_todo_lists_what_needs_a_human(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(), _report()))
    todo = setup_cmd._setup_core(yes=True)["todo"]
    assert not any("login" in t for t in todo)
    assert any("cv.md" in t and "/onboard" in t for t in todo)
    assert not any("/expand" in t for t in todo)
    assert any("search_keywords" in t and "/onboard" in t for t in todo)


def test_setup_tool_never_prompts_and_uses_sudo_n(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(latex="missing"), _report()))
    assert server.setup()["outcome"] == "needs_confirmation"
    assert env.ran == []
    assert server.setup(install=["latex"], yes=True)["outcome"] == "ok"
    assert env.ran == [LATEX_ARGV_N]


# --------------------------------------------------------------------------- #
# setup command: list everything, ask once, install each with a progress line
# --------------------------------------------------------------------------- #

def test_setup_cli_lists_every_tool_and_asks_once(env, monkeypatch, prompts):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(latex="missing"), _report()))
    result = CliRunner().invoke(cli, ["doctor", "--fix"])
    assert prompts.order == ["install"]
    assert prompts.asked["install"]["default"] is True
    out = result.output
    assert out.index("Tectonic") < out.index("claude CLI")
    assert "already installed" in out
    assert env.ran == [LATEX_ARGV]
    assert "✓ Tectonic" in out
    assert result.exit_code == 0, result_text(result)


def test_setup_cli_declined_installs_nothing(env, monkeypatch, prompts):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(latex="missing")))
    prompts.answers.update(install=False)
    result = CliRunner().invoke(cli, ["doctor", "--fix"])
    assert env.ran == []
    assert result.exit_code == 1


def test_setup_cli_yes_never_asks(env, monkeypatch, prompts):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(latex="missing", claude="missing"), _report()))
    result = CliRunner().invoke(cli, ["doctor", "--fix", "--yes"])
    assert prompts.order == []
    assert env.ran == [LATEX_ARGV, CLAUDE_ARGV]
    assert result.exit_code == 0, result_text(result)


def test_setup_cli_nothing_to_install_does_not_ask(env, monkeypatch, prompts):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report()))
    result = CliRunner().invoke(cli, ["doctor", "--fix"])
    assert prompts.order == [] and env.ran == []
    assert result.exit_code == 0, result_text(result)


def test_setup_cli_reports_a_failed_install(env, monkeypatch):
    def failing(argv, **kwargs):
        env.ran.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, "", "network down")

    monkeypatch.setattr(subprocess, "run", failing)
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(latex="missing"), _report(latex="missing")))
    result = CliRunner().invoke(cli, ["doctor", "--fix", "--yes"])
    assert "✗ Tectonic" in result.output and "network down" in result_text(result)
    assert result.exit_code == 1


def test_setup_cli_no_tex_and_no_claude(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(latex="missing", claude="missing")))
    result = CliRunner().invoke(cli, ["doctor", "--fix", "--yes", "--no-tex", "--no-claude"])
    assert env.ran == []
    assert result.exit_code == 1


def test_setup_cli_ends_with_a_live_mcp_handshake(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report()))
    result = CliRunner().invoke(cli, ["doctor", "--fix", "--yes"])
    assert "✓ MCP server" in result.output

    monkeypatch.setattr(doctor, "probe_mcp_server", lambda *a, **k: _check("mcp server", "missing", fix="re-run ./scripts/setup.sh"))
    result = CliRunner().invoke(cli, ["doctor", "--fix", "--yes"])
    assert "✗ MCP server" in result.output
    assert result.exit_code == 1


def test_setup_cli_registers_the_server_locally_where_mcp_json_cannot_start_it(env, monkeypatch, tmp_path):
    """.mcp.json names .venv/bin/python, which Windows venvs don't have."""
    monkeypatch.setattr(setup_cmd, "_detect_platform", lambda: "windows")
    monkeypatch.setattr(shutil, "which", lambda name: "C:/bin/claude.cmd" if name == "claude" else None)
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".mcp.json").write_text('{"mcpServers": {"door": {"command": ".venv/bin/python", "args": ["-m", "door.mcp_server"]}}}')
    monkeypatch.setattr(workspace, "REPO_ROOT", root)
    monkeypatch.setattr(workspace, "HOME", root)
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report()))
    result = CliRunner().invoke(cli, ["doctor", "--fix", "--yes"])
    python = str(root / ".venv" / "Scripts" / "python.exe")
    assert [
        "C:/bin/claude.cmd", "mcp", "add", "--scope", "local", "door", "-e", f"PYTHONPATH={root / 'src'}",
        "--", python, "-m", "door.mcp_server",
    ] in env.ran
    assert result.exit_code == 0, result_text(result)


def test_setup_cli_points_at_onboard_for_the_profile(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(profile="missing")))
    result = CliRunner().invoke(cli, ["doctor", "--fix", "--yes"])
    assert "/onboard" in result.output
    assert result.exit_code == 0, result_text(result)  # the profile is /onboard's job, not setup's


def test_setup_cli_does_not_probe_the_sites_unless_asked(env, monkeypatch):
    probes = []
    real = Sequence(_report())
    monkeypatch.setattr(doctor, "run_checks", lambda *a, **k: probes.append(k.get("probe_sites")) or real())
    CliRunner().invoke(cli, ["doctor", "--fix", "--yes"])
    assert not any(probes)


# --------------------------------------------------------------------------- #
# Tectonic
# --------------------------------------------------------------------------- #

def test_compile_prefers_tectonic(env, monkeypatch):
    out = env.jobs_dir / "output" / "jobindex-acme-ds"
    out.mkdir(parents=True)
    (out / "cv.tex").write_text("x")
    monkeypatch.setattr(compile_cmd, "_find_tectonic", lambda: "/home/me/.local/bin/tectonic")
    result = compile_cmd._compile_core("jobindex-acme-ds", jobs_dir=env.jobs_dir)
    assert result["results"][0]["compiler"] == "tectonic"
    assert env.ran[0][:3] == ["/home/me/.local/bin/tectonic", "--outdir", str(out)]


def test_doctor_accepts_tectonic():
    check = doctor.check_latex(which=lambda name: "/usr/bin/tectonic" if name == "tectonic" else None)
    assert check["status"] == "ok"
    assert "tectonic" in check["detail"]


# --------------------------------------------------------------------------- #
# scraper-fix offers (issue #178)
# --------------------------------------------------------------------------- #

def _drift_report(status="drift", fixable=True, site="jobindex"):
    report = _report()
    report["checks"].append({
        "name": f"scraper: {site}", "status": status, "required": False,
        "detail": "no results block (raw response: jobs/drift/x)", "fix": "choose `fix scraper` in `setup`",
        "fixable": fixable,
    })
    return report


@pytest.fixture
def fixer(monkeypatch):
    from door.core import scraper_fix

    calls = []

    def fake(site, **kw):
        calls.append((site, kw))
        return {"site": site, "outcome": "pr", "branch": "fix/scraper-jobindex-x", "url": "https://github.com/o/r/pull/9"}

    monkeypatch.setattr(scraper_fix, "fix_scraper", fake)
    return calls


def test_setup_core_plan_lists_fixable_scrapers_and_runs_nothing(env, fixer, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_drift_report()))
    result = setup_cmd._setup_core()
    assert [f["site"] for f in result["fixes"]] == ["jobindex"]
    assert result["fixes"][0]["check"]["status"] == "drift"
    assert fixer == []


def test_setup_core_does_not_offer_walls_or_unreachable_sites(env, fixer, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_drift_report(status="warn", fixable=False)))
    assert setup_cmd._setup_core()["fixes"] == []


def test_setup_core_runs_only_the_named_fix_with_yes(env, fixer, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_drift_report(), _drift_report()))
    setup_cmd._setup_core(yes=True)
    assert fixer == []  # a fix must be asked for by name
    result = setup_cmd._setup_core(fix_scrapers=["jobindex"], yes=True)
    assert [c[0] for c in fixer] == ["jobindex"]
    assert result["fixes"][0]["outcome"] == "pr" and result["fixes"][0]["url"].endswith("/9")
    assert fixer[0][1]["repo_root"] == workspace.REPO_ROOT


def test_setup_core_reuses_a_given_report_and_hands_unoffered_sites_a_non_fixable_check(env, fixer, monkeypatch):
    def no_checks(*a, **k):
        raise AssertionError("must reuse the report")

    monkeypatch.setattr(doctor, "run_checks", no_checks)
    result = setup_cmd._setup_core(install=[], fix_scrapers=["lever"], yes=True, report=_drift_report())
    assert result["fixes"][0]["site"] == "lever"
    assert fixer[0][1]["check"]["status"] == "none"  # fix_scraper refuses a site that has no drift check


def test_setup_core_reports_a_lock_conflict_as_an_error(env, monkeypatch):
    from door.core import lock, scraper_fix

    def held(site, **kw):
        raise lock.LockHeldError("a run is in progress")

    monkeypatch.setattr(scraper_fix, "fix_scraper", held)
    monkeypatch.setattr(doctor, "run_checks", Sequence(_drift_report()))
    result = setup_cmd._setup_core(fix_scrapers=["jobindex"], yes=True)
    assert result["fixes"] == [{"site": "jobindex", "outcome": "refused", "error": "a run is in progress"}]


def test_setup_cli_offers_the_fix_and_asks_first(env, fixer, monkeypatch, prompts):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_drift_report()))
    result = CliRunner().invoke(cli, ["doctor", "--fix", "--probe"])
    assert prompts.asked["fix_jobindex"] == {"kind": "confirm", "message": "Fix scraper: jobindex?", "default": False}
    assert result.exit_code == 0, result_text(result)
    assert "fix scraper: jobindex" in result.output
    assert fixer == []


def test_setup_cli_runs_the_fix_when_approved_and_prints_the_pr(env, fixer, monkeypatch, prompts):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_drift_report()))
    prompts.answers.update(fix_jobindex=True)
    result = CliRunner().invoke(cli, ["doctor", "--fix", "--probe"])
    assert result.exit_code == 0, result_text(result)
    assert [c[0] for c in fixer] == ["jobindex"]
    assert "https://github.com/o/r/pull/9" in result.output


def test_setup_cli_yes_runs_the_fix_without_asking(env, fixer, monkeypatch, prompts):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_drift_report()))
    result = CliRunner().invoke(cli, ["doctor", "--fix", "--yes", "--probe"])
    assert result.exit_code == 0, result_text(result)
    assert [c[0] for c in fixer] == ["jobindex"]
    assert prompts.order == []


def test_setup_cli_prints_fallback_commands_and_failures(env, monkeypatch):
    from door.core import scraper_fix

    outcomes = iter([
        {"site": "jobindex", "outcome": "local_branch", "branch": "fix/b", "commands": ["git push -u origin fix/b"]},
        {"site": "jobindex", "outcome": "gate_failed", "detail": "offline tests failed"},
    ])
    monkeypatch.setattr(scraper_fix, "fix_scraper", lambda site, **kw: next(outcomes))
    monkeypatch.setattr(doctor, "run_checks", Sequence(_drift_report()))
    out = CliRunner().invoke(cli, ["doctor", "--fix", "--yes", "--probe"]).output
    assert "fix/b" in out and "git push -u origin fix/b" in out
    out = CliRunner().invoke(cli, ["doctor", "--fix", "--yes", "--probe"]).output
    assert "offline tests failed" in out




def test_setup_cli_output_is_sectioned(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(latex="missing"), _report()))
    out = CliRunner().invoke(cli, ["doctor", "--fix", "--yes"]).output
    assert out.index("Tools") < out.index("Tectonic") < out.index("MCP server") < out.index("Next")
    assert "/onboard" in out[out.index("Next"):]


def test_setup_cli_says_setup_complete_when_nothing_is_left(env, monkeypatch, tmp_path):
    example = tmp_path / "example"
    example.mkdir()
    (example / "cv.md").write_text("# Example")
    monkeypatch.setattr(workspace, "PROFILE_EXAMPLE_DIR", example)
    (env.profile_dir / "cv.md").write_text("# Me")
    write_config(env.profile_dir, {"role_targets": ["x"], "location": "Copenhagen", "search_keywords": ["x"]})
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report()))
    result = CliRunner().invoke(cli, ["doctor", "--fix", "--yes"])
    assert result.exit_code == 0, result_text(result)
    assert "✓ Setup complete." in result.output
    assert "Next" not in result.output.split("MCP server", 1)[1]


def test_setup_cli_names_what_is_missing_on_stderr(env, monkeypatch, prompts):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(latex="missing")))
    prompts.answers.update(install=False)
    result = CliRunner().invoke(cli, ["doctor", "--fix"])
    assert "✗ Missing: latex — apt-get install texlive-xetex" in result_text(result)
    assert result.exit_code == 1


def test_setup_cli_marks_each_scraper_fix_outcome(env, monkeypatch):
    from door.core import scraper_fix

    outcomes = iter([
        {"site": "jobindex", "outcome": "pr", "branch": "fix/a", "url": "https://github.com/o/r/pull/9"},
        {"site": "jobindex", "outcome": "local_branch", "branch": "fix/b", "commands": ["git push -u origin fix/b"]},
        {"site": "jobindex", "outcome": "gate_failed", "detail": "offline tests failed"},
    ])
    monkeypatch.setattr(scraper_fix, "fix_scraper", lambda site, **kw: next(outcomes))
    monkeypatch.setattr(doctor, "run_checks", Sequence(_drift_report()))
    out = CliRunner().invoke(cli, ["doctor", "--fix", "--yes", "--probe"]).output
    assert "Scrapers" in out and "⚠ fix scraper: jobindex" in out
    assert "✓ jobindex: PR opened https://github.com/o/r/pull/9" in out
    out = CliRunner().invoke(cli, ["doctor", "--fix", "--yes", "--probe"]).output
    assert "⚠ jobindex: fix committed on branch fix/b" in out and "$ git push -u origin fix/b" in out
    out = CliRunner().invoke(cli, ["doctor", "--fix", "--yes", "--probe"]).output
    assert "✗ jobindex: gate_failed — offline tests failed" in out


def test_setup_cli_colours_the_marks_on_a_terminal(env, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", Sequence(_report(latex="missing"), _report()))
    out = CliRunner().invoke(cli, ["doctor", "--fix", "--yes"], color=True).output
    assert "\x1b[32m✓\x1b[0m Tectonic" in out          # installed: green
    assert "\x1b[32m✓\x1b[0m claude CLI" in out        # already there: green too
    plain = CliRunner().invoke(cli, ["doctor", "--fix", "--yes"]).output
    assert "\x1b[" not in plain


def test_progress_spinner_is_yellow(monkeypatch, capsys):
    from door.commands import _progress

    monkeypatch.setattr(_progress.sys.stdout, "isatty", lambda: True, raising=False)
    _progress.step("Thing", lambda: (_progress.time.sleep(0.15), (True, None))[1])
    assert "\x1b[33m⠋\x1b[0m Thing" in capsys.readouterr().out


def test_doctor_install_flags_need_fix(cli_env):
    for flag in ("--yes", "--no-tex", "--no-claude"):
        result = CliRunner().invoke(cli, ["doctor", flag])
        assert result.exit_code == 2, flag
        assert "only go with --fix" in result_text(result)


def _render_checks(checks):
    from io import StringIO
    from rich.console import Console

    buf = StringIO()
    setup_cmd._print_checks(Console(file=buf, width=120, force_terminal=False), checks)
    return buf.getvalue()


def test_print_checks_shows_the_connected_account():
    check = {**_check("claude login", "ok"), "details": {"email": "jane@example.com", "subscriptionType": "pro", "orgName": "Jane Org"}}
    out = _render_checks([check])
    assert "Connected as jane@example.com (pro, Jane Org)" in out


def test_print_checks_without_details_has_no_account_line():
    assert "Connected as" not in _render_checks([_check("claude login", "ok")])
    assert "Connected as" not in _render_checks([{**_check("claude login", "ok"), "details": {"loggedIn": True}}])


# --------------------------------------------------------------------------- #
# A download that fails fails the install (#586)
# --------------------------------------------------------------------------- #

def _stand_in_curl(tmp_path, monkeypatch, body: str):
    """A `curl` first on PATH: the planned shell command really runs, against it, offline."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text("#!/bin/sh\n" + body + "\n")
    curl.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.mark.parametrize("tool", ["claude", "latex"])
def test_an_installer_that_cannot_be_downloaded_fails_with_curls_error(tool, tmp_path, monkeypatch):
    _stand_in_curl(tmp_path, monkeypatch, 'echo "curl: (7) Failed to connect" >&2; exit 7')
    step = installers.plan_install(tool, "macos", which=lambda n: "/usr/bin/curl" if n == "curl" else None, home=tmp_path)
    result = setup_cmd._install_step(step)
    assert result["ok"] is False
    assert "Failed to connect" in result["error"]


def test_a_downloaded_installer_runs(tmp_path, monkeypatch):
    _stand_in_curl(tmp_path, monkeypatch, "echo 'touch \"$HOME/installed\"'")
    step = installers.plan_install("claude", "macos", which=lambda n: "/usr/bin/curl" if n == "curl" else None, home=tmp_path)
    assert setup_cmd._install_step(step)["ok"] is True
    assert (tmp_path / "installed").exists()
