"""`doctor`: check prerequisites; with `--fix`, install what is missing and offer scraper fixes."""

import shutil
import subprocess
import sys
from pathlib import Path

import click

from door.commands import _common as common
from door.commands import _progress
from door.commands import _prompts
from door.core import workspace


# --------------------------------------------------------------------------- #
# doctor (issue #138)
# --------------------------------------------------------------------------- #
def _doctor_core(profile_dir: Path | None = None, jobs_dir: Path | None = None, *, probe: bool = False) -> dict:
    """Check every prerequisite and report the last run and scrapes. Never prints.

    The checks are local and instant. With ``probe`` each configured
    site also gets a live ``scraper: <site>`` probe (page 1 of the first
    keyword), which is what finds a
    scraper whose site changed.

    Returns:
        `door.core.doctor.run_checks`'s dict: ``{"ok", "checks": [{"name",
        "status": "ok"|"missing"|"warn"|"drift", "required", "detail", "fix"}, ...],
        "last_run", "last_scrape"}`` — ``ok`` is False when any required
        tool is missing; ``drift``/``warn`` never fail ``ok``.
    """
    from door.core import doctor

    return doctor.run_checks(
        profile_dir if profile_dir is not None else workspace.PROFILE_DIR,
        jobs_dir if jobs_dir is not None else workspace.JOBS_DIR,
        probe_sites=probe,
        probe=_reporting_probe if probe else None,
    )


def _reporting_probe(site: str, config: dict, profile_dir: Path):
    """`doctor.default_probe`, announcing the site to the active progress reporter first."""
    from door.core import doctor, progress

    progress.report(f"probing {site}…", site=site, stage="probe")
    return doctor.default_probe(site, config, profile_dir)


def _check_kind(check: dict) -> str:
    """A check's mark: ✓ ok, ✗ a required tool missing or a scraper that no longer
    fits its site (drift), ⚠ anything optional or a wall/unreachable site."""
    status = check["status"]
    if status == "ok":
        return "ok"
    if status == "drift" or (status == "missing" and check.get("required", True)):
        return "fail"
    return "warn"


@click.command()
@click.option("--probe", "probe", is_flag=True, default=False, help="Also probe each configured site live for a scraper that no longer fits it (slow). With --fix, offer to repair a drifted one.")
@click.option("--fix", "fix", is_flag=True, default=False, help="Install what is missing (Tectonic, the claude CLI), then check the MCP server starts.")
@click.option("--yes", is_flag=True, default=False, help="With --fix: install without asking.")
@click.option("--no-tex", "no_tex", is_flag=True, default=False, help="With --fix: don't install a TeX engine.")
@click.option("--no-claude", "no_claude", is_flag=True, default=False, help="With --fix: don't install the claude CLI.")
def doctor(probe: bool, fix: bool, yes: bool, no_tex: bool, no_claude: bool):
    """Check prerequisites (Python, profile, LaTeX, `claude`, the MCP server); --fix installs what is missing.

    Prints a "Prerequisites" section, one ✓/⚠/✗ line per check with the fix
    under anything missing, then the last run and each site's last scrape.
    With --probe each configured site also gets a live probe (page 1 only),
    shown under "Live probes": ✗ means its page no longer has the structure
    the scraper reads, ⚠ a wall or an unreachable site; the raw response is
    saved under jobs/drift/<site>/. Exit 1 only if a required tool is missing.

    With --fix: lists Tectonic (LaTeX) and the claude CLI
    with what is already there, asks once (--yes skips the question),
    installs the rest with one progress line each, and ends with a live
    handshake with the MCP server Claude Code will start
    (./scripts/setup.sh ends with this). Safe to re-run — it is the repair
    command. With --probe too, a drifted scraper is offered a fix: after
    asking, the scraper-fixer agent repairs it on a new branch, the offline
    tests and a fresh probe gate it, and a PR is opened (or the branch and
    commands are printed when push or `gh` is unavailable). Exit 0 only when
    every required tool is in place and the MCP server answers.
    """
    if not fix:
        if yes or no_tex or no_claude:
            raise click.UsageError("--yes, --no-tex and --no-claude only go with --fix.")
        _check(probe)
        return
    _fix(yes, no_tex, no_claude, fix_scrapers=probe)


def _err_console():
    """`common._console()`'s twin on stderr, for the closing failure lines."""
    from rich.console import Console

    return Console(stderr=True, force_terminal=common._stdout_is_tty(), highlight=False, width=common._console().width)


def _print_checks(console, checks: list[dict], *, strip: str = "") -> None:
    """One ✓/⚠/✗ line per check (names aligned, detail dim), the fix dim on the line below."""
    from rich.text import Text

    width = max((len(c["name"]) - len(strip) for c in checks), default=0)
    for check in checks:
        name = check["name"][len(strip):]
        line = Text.assemble((name.ljust(width), "bold"), "  ", (check["detail"] or "", "dim" if check["status"] == "ok" else ""))
        common._mark_line(console, _check_kind(check), line)
        if check["fix"]:
            console.print(Text.assemble("      ", ("fix: ", "dim"), (check["fix"], "dim")), soft_wrap=True)
        account = _account_line(check.get("details"))
        if account:
            console.print(Text.assemble("      ", (account, "dim")), soft_wrap=True)


def _account_line(details: dict | None) -> str | None:
    """`Connected as jane@x.com (pro, Org)` from a login check's `details`; None without an email."""
    details = details or {}
    if not details.get("email"):
        return None
    extra = ", ".join(str(details[k]) for k in ("subscriptionType", "orgName") if details.get(k))
    return f"Connected as {details['email']}" + (f" ({extra})" if extra else "")


def _print_last_run(console, last: dict | None, last_scrape: list[dict]) -> None:
    from rich.text import Text

    common._section(console, "Last run")
    if last is None:
        common._mark_line(console, "info", Text("none yet"))
        common._next_steps(console, [("./door find", "fetch and score new jobs")])
    else:
        outcome = Text(last["outcome"], style="green" if last["outcome"] == "ok" else "red")
        console.print(common._kv_grid([
            ("When", common._local_time(last["started_at"]) if last.get("started_at") else "?"),
            ("Outcome", outcome),
            ("Failures", Text(", ".join(last["failures"]), style="red") if last["failures"] else None),
            ("New matches", str(last["new_above_threshold"]) if last.get("new_above_threshold") is not None else None),
        ]))
    if last_scrape:
        common._section(console, "Last scrape")
        console.print(common._kv_grid([
            (row["site"], common._local_time(row["last_success"]) if row["last_success"]
             else Text("never (first scrape looks back max_age_days)", style="dim"))
            for row in last_scrape
        ]))


def _check(probe: bool) -> None:
    """`doctor` without --fix: print every check, the last run and the last scrapes."""
    from rich.text import Text

    from door.core import progress

    with _progress.live_progress(probe and common._stdout_is_tty()) as live:
        with progress.activate(live):
            result = _doctor_core(workspace.PROFILE_DIR, workspace.JOBS_DIR, probe=probe)

    console = common._console()
    prefix = "scraper: "
    checks = [c for c in result["checks"] if not c["name"].startswith(prefix)]
    probes = [c for c in result["checks"] if c["name"].startswith(prefix)]
    console.print(f"  [dim]data folder: {result.get('home') or workspace.HOME}[/]", soft_wrap=True, markup=True, highlight=False)
    common._section(console, "Prerequisites")
    _print_checks(console, checks)
    if probes:
        common._section(console, "Live probes")
        _print_checks(console, probes, strip=prefix)
    _print_last_run(console, result["last_run"], result["last_scrape"])

    console.print()
    if result["ok"]:
        common._mark_line(console, "ok", "All required prerequisites are in place.")
    else:
        missing = [c["name"] for c in result["checks"] if c["status"] == "missing"]
        common._mark_line(_err_console(), "fail", Text(f"Missing: {', '.join(missing)}."))
        sys.exit(1)


# --------------------------------------------------------------------------- #
# setup (issue #141)
# --------------------------------------------------------------------------- #

def _detect_platform() -> str:
    """`installers.detect_platform()` for this machine (monkeypatched in tests)."""
    from door.core.installers import detect_platform

    return detect_platform()


_ONBOARD = "open Claude Code here (`claude`) and say /onboard"


def _setup_todo(report: dict, profile_dir: Path, example_dir: Path, skip_profile: bool) -> list[str]:
    """What still needs a human after the installs: CV, keywords, profile."""
    todo = []
    profile_ok = any(c["name"] == "profile" and c["status"] == "ok" for c in report["checks"])
    if not profile_ok:
        todo.append(f"create your profile: {_ONBOARD}")
        return todo
    cv, example_cv = profile_dir / "cv.md", example_dir / "cv.md"
    if not cv.is_file() or (example_cv.is_file() and cv.read_bytes() == example_cv.read_bytes()):
        todo.append(f"turn your CV into profile/cv.md: {_ONBOARD}")
    if not common._load_config_or_defaults(profile_dir).get("search_keywords"):
        todo.append("populate search_keywords: ask Claude to \"expand my search keywords\", or run /onboard (optional)")
    return todo


def _install_step(step: dict, interactive: bool = False) -> dict:
    """Run one planned tool's commands in order, stopping at the first failure.

    Returns ``{"tool", "ok", "ran": [argv...], "error"?}``; output is captured
    (and its tail kept in ``error``) unless ``interactive``.
    """
    entry = {"tool": step["tool"], "ok": bool(step["commands"]), "ran": []}
    if not step["commands"]:
        entry["error"] = step["hint"]
    for argv in step["commands"]:
        entry["ran"].append(argv)
        try:
            # interactive (a shell): an installer may ask on the keyboard; else nothing to read
            proc = subprocess.run(argv, capture_output=not interactive, text=True,
                                  stdin=None if interactive else subprocess.DEVNULL)
        except FileNotFoundError:
            entry.update(ok=False, error=f"`{argv[0]}` not found")
            break
        if proc.returncode != 0:
            detail = ((proc.stderr or proc.stdout or "") if not interactive else "").strip()
            entry.update(ok=False, error=f"`{' '.join(argv)}` exited {proc.returncode}" + (f": {detail[-300:]}" if detail else ""))
            break
    return entry


def _setup_core(
    install: list[str] | None = None,
    yes: bool = False,
    skip_profile: bool = True,
    *,
    interactive: bool = False,
    profile_dir: Path | None = None,
    jobs_dir: Path | None = None,
    fix_scrapers: list[str] | None = None,
    report: dict | None = None,
    probe_sites: bool = False,
) -> dict:
    """Install the missing prerequisites `doctor` reports. Never prints.

    Without ``yes`` nothing runs: the plan (exact argv per tool) comes back
    for the user to approve. With ``yes`` each planned tool's commands run in
    order (a tool stops at its first failing command), then `doctor` runs
    again. The profile is not created here — the CLI runs `init`'s prompts,
    the conversation uses `init_profile`.

    Args:
        install: Tools to install ("latex", "claude"); None
            means every tool whose required check fails.
        yes: The user approved the plan — run it.
        skip_profile: Don't count a missing profile against ``outcome``.
        interactive: A person is at the terminal: `sudo` may prompt and the
            commands' output streams through. Otherwise `sudo -n` (fail
            fast instead of hanging) and output is captured.
        fix_scrapers: Sites whose drifted scraper to repair (with ``yes``):
            each runs the headless scraper-fixer on a fix branch, gates it
            and opens a PR (`door.core.scraper_fix`). Never run unless
            named here.
        report: A `doctor` report to reuse instead of running the checks
            again (the CLI passes the one it already has).
        probe_sites: Probe each configured site live (as `doctor --probe`)
            so ``fixes`` can offer a drifted scraper; implied by
            ``fix_scrapers``. Off by default: the installs need no network.

    Returns:
        ``{"outcome": "needs_confirmation" | "ok" | "incomplete",
        "platform", "plan": [{"tool", "commands", "hint", "note"}],
        "results": [{"tool", "ok", "ran": [argv...], "error"?}], "doctor":
        <run_checks>, "todo": [str, ...], "fixes": [...]}``. ``fixes`` is the
        offer — ``[{"site", "check"}]`` for each ``scraper: <site>`` check
        with a code-level drift — until fixes run, then one outcome per site:
        ``{"site", "outcome": "pr" | "local_branch" | "gate_failed" |
        "fixer_failed" | "refused", "url"?, "branch"?, "commands"?,
        "detail"?, "error"?}``.

    Raises:
        ValueError: `install` names an unknown tool.
    """
    from door.core import doctor
    from door.core.installers import INSTALLABLE, TOOL_FOR_CHECK, plan_install

    profile_dir = profile_dir if profile_dir is not None else workspace.PROFILE_DIR
    jobs_dir = jobs_dir if jobs_dir is not None else workspace.JOBS_DIR
    platform = _detect_platform()

    probe_sites = probe_sites or bool(fix_scrapers)
    before = report if report is not None else doctor.run_checks(profile_dir, jobs_dir, probe_sites=probe_sites)
    offered = [
        {"site": c["name"].split(": ", 1)[1], "check": c} for c in before["checks"]
        if c["name"].startswith("scraper: ") and c["status"] in ("drift", "warn") and c.get("fixable")
    ]
    if install is None:
        tools = [
            TOOL_FOR_CHECK[c["name"]] for c in before["checks"]
            if c["name"] in TOOL_FOR_CHECK and c["status"] == "missing"
        ]
    else:
        unknown = [t for t in install if t not in INSTALLABLE]
        if unknown:
            raise ValueError(f"unknown tool(s): {', '.join(unknown)} (installable: {', '.join(INSTALLABLE)})")
        tools = list(install)

    plan = [plan_install(t, platform, which=shutil.which) for t in tools]
    result = {"outcome": "needs_confirmation", "platform": platform, "plan": plan, "results": [], "doctor": before, "todo": [], "fixes": offered}
    if not yes:
        return result

    for step in plan:
        result["results"].append(_install_step(step, interactive))

    after = doctor.run_checks(profile_dir, jobs_dir) if plan else before
    missing = [c for c in after["checks"] if c["status"] == "missing" and not (skip_profile and c["name"] == "profile")]
    result.update(
        outcome="incomplete" if missing else "ok",
        doctor=after,
        todo=_setup_todo(after, profile_dir, workspace.PROFILE_EXAMPLE_DIR, skip_profile),
    )
    if fix_scrapers:
        result["fixes"] = _setup_run_fixes(fix_scrapers, before, profile_dir, jobs_dir)
    return result


def _setup_run_fixes(sites: list[str], report: dict, profile_dir: Path, jobs_dir: Path) -> list[dict]:
    """Run the gated scraper fix for each named site; one outcome dict per site."""
    from door.core import scraper_fix
    from door.core.lock import LockHeldError

    checks = {c["name"]: c for c in report["checks"]}
    outcomes = []
    for site in sites:
        check = checks.get(f"scraper: {site}") or {"status": "none"}
        try:
            outcomes.append(scraper_fix.fix_scraper(
                site, jobs_dir=jobs_dir, repo_root=workspace.REPO_ROOT, profile_dir=profile_dir, check=check,
            ))
        except LockHeldError as exc:
            outcomes.append({"site": site, "outcome": "refused", "error": str(exc)})
    return outcomes


def _setup_fix_pass(yes: bool) -> dict:
    """Probe the sites once, offer the drifted-scraper repairs, ask first, run and
    print each outcome; return the probed doctor report."""
    plan = _setup_core(install=[], skip_profile=True, probe_sites=True)
    report, offers = plan["doctor"], plan["fixes"]
    from rich.text import Text

    console = common._console()
    if offers:
        common._section(console, "Scrapers")
    approved = []
    for offer in offers:
        common._mark_line(console, "warn", Text(f"fix scraper: {offer['site']} — {offer['check']['detail']}"))
        console.print("      [dim]runs the scraper-fixer agent on a new branch, gates it on the tests and a fresh probe, opens a PR[/]", soft_wrap=True)
        if yes or _prompts.confirm(f"fix_{offer['site']}", f"Fix scraper: {offer['site']}?", default=False):
            approved.append(offer["site"])
    if not approved:
        return report
    result = _setup_core(install=[], fix_scrapers=approved, yes=True, report=report, skip_profile=True, interactive=True)
    for fix in result["fixes"]:
        outcome = fix["outcome"]
        if outcome == "pr":
            common._mark_line(console, "ok", Text(f"{fix['site']}: PR opened {fix['url']} (branch {fix['branch']})"))
        elif outcome == "local_branch":
            common._mark_line(console, "warn", Text(f"{fix['site']}: fix committed on branch {fix['branch']}; finish by hand:"))
            for command in fix["commands"]:
                console.print(Text.assemble("      ", ("$ ", "dim"), (command, "bold")), soft_wrap=True)
        else:
            common._mark_line(console, "fail", Text(f"{fix['site']}: {outcome} — {fix.get('detail') or fix.get('error')}"))
    return report


_TOOL_LABELS = {"latex": "Tectonic (LaTeX)", "claude": "claude CLI"}


def _register_mcp_server(platform: str) -> tuple[bool, str | None]:
    """Where `.mcp.json`'s interpreter does not exist (Windows venvs have no
    bin/python), register a local-scope entry for the venv's real interpreter;
    then check the server answers the way Claude Code will start it."""
    from door.core import doctor
    from door.core.installers import plan_mcp_registration

    if doctor._custom_home():   # the tailor's .mcp.json is generated for this interpreter, nothing to register
        check = doctor.check_generated_mcp()
        return check["status"] == "ok", None if check["status"] == "ok" else f"{check['detail']} — {check['fix']}"
    step = plan_mcp_registration(workspace.REPO_ROOT, platform, which=shutil.which)
    if step is not None:
        if not step["commands"]:
            return False, step["hint"]
        subprocess.run(step["cleanup"], capture_output=True, text=True, stdin=subprocess.DEVNULL)  # a stale entry from an earlier setup
        entry = _install_step(step)
        if not entry["ok"]:
            return False, entry["error"]
    check = doctor.probe_mcp_server(workspace.REPO_ROOT)
    return check["status"] == "ok", None if check["status"] == "ok" else f"{check['detail']} — {check['fix']}"


def _fix(yes: bool, no_tex: bool, no_claude: bool, fix_scrapers: bool) -> None:
    """`doctor --fix`: install what is missing, check the MCP server, optionally fix drifted scrapers."""
    from rich.text import Text

    from door.core import doctor
    from door.core.installers import TOOL_FOR_CHECK

    report = doctor.run_checks(workspace.PROFILE_DIR, workspace.JOBS_DIR)
    status = {TOOL_FOR_CHECK[c["name"]]: c["status"] for c in report["checks"] if c["name"] in TOOL_FOR_CHECK}
    skipped = {t for t, flag in (("latex", no_tex), ("claude", no_claude)) if flag}
    tools = [t for t in _TOOL_LABELS if status.get(t) not in (None, "ok") and t not in skipped]

    console = common._console()
    common._section(console, "Tools")
    for tool, label in _TOOL_LABELS.items():
        state = "already installed" if status.get(tool) == "ok" else ("skipped" if tool in skipped else "to install")
        if state != "to install" or not yes:  # with --yes, what gets installed shows as its progress line
            glyph = _progress.CHECK if state == "already installed" else "·"
            click.echo(f"  {glyph} {label:<22}{click.style(state, dim=True)}")

    if tools and (yes or _prompts.confirm("install", f"Install {len(tools)} missing tool{'s' * (len(tools) > 1)}?", default=True)):
        plan = _setup_core(install=tools, report=report)["plan"]
        if any(argv[:1] == ["sudo"] for step in plan for argv in step["commands"]) and sys.stdin.isatty():
            subprocess.run(["sudo", "-v"], stdin=None)  # ask for the password once, before the spinners: the keyboard
        plan = [{**step, "commands": [["sudo", "-n", *argv[1:]] if argv[:1] == ["sudo"] else argv for argv in step["commands"]]} for step in plan]
        for step in plan:
            _progress.step(_TOOL_LABELS[step["tool"]], lambda step=step: (lambda e: (e["ok"], e.get("error")))(_install_step(step)))
            if step.get("note"):
                click.echo(click.style(f"      {step['note']}", dim=True))
        report = doctor.run_checks(workspace.PROFILE_DIR, workspace.JOBS_DIR)

    mcp_ok = _progress.step("MCP server", lambda: _register_mcp_server(_detect_platform()))

    if fix_scrapers:
        report = _setup_fix_pass(yes)

    missing = [c for c in report["checks"] if c["status"] == "missing" and c["name"] != "profile"]
    login = next((c for c in report["checks"] if c["name"] == "claude login" and c["status"] != "ok"), None)
    todo = _setup_todo(report, workspace.PROFILE_DIR, workspace.PROFILE_EXAMPLE_DIR, True)
    console.print()
    err = _err_console()
    for c in missing:
        common._mark_line(err, "fail", Text(f"Missing: {c['name']} — {c['fix']}"))
    if login:
        common._mark_line(console, "warn", Text(f"claude: {login['detail']} — {login['fix']}"))
    if missing or not mcp_ok:
        sys.exit(1)
    if todo:
        common._section(console, "Next")
        for item in todo:
            common._mark_line(console, "info", Text(item))
    else:
        common._mark_line(console, "ok", Text("Setup complete. In Claude Code, say \"get me today's jobs\"."))
