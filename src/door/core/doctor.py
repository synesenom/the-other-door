"""Prerequisite checks for `door doctor` (issue #138).

Each check is a pure function over injectable probes (`which`, paths, `now`)
and returns a dict:

    {"name", "status": "ok" | "missing" | "warn" | "drift", "required": bool,
     "detail": str, "fix": str | None}

``missing`` is a required tool that is absent (doctor exits non-zero);
``warn`` is something optional or stale; ``drift`` is a scraper whose live
site no longer has the structure it parses (``scraper: <site>`` checks, from
each scraper's ``probe()``; non-fatal, offered a fix by ``doctor --probe --fix``). `run_checks` runs them all and adds
two informational blocks: the last recorded run (`jobs/runs/`) and each
configured site's last successful scrape (`jobs/scrape_state.json`, the
watermark `scrape` counts from).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from door.core import claude_cli, companies, discovery_sources, installers, migrations, runs, sites
from door.core.sites import FEED_SITES
from door.scrapers import PROBE_TIMEOUT_S, ProbeResult  # noqa: F401 - re-exported
from door.scrapers import http_client

MIN_PYTHON = (3, 12)
# Scraper probe plausibility (issue #178). Run records hold post-filter counts,
# so history undercounts page 1: both rules are deliberately loose.
MIN_AVG_FOR_ZERO_WARN = 3   # warn on 0 results only where runs average at least this
HIGH_FACTOR = 5             # warn when page 1 alone exceeds this multiple of the average
HISTORY_RUNS = 10           # how many recent run records the average spans
DEV_MODULES = ("pytest", "responses", "genbadge")

_LATEX_FIX = "./door doctor --fix   (installs Tectonic, no sudo)"

def _check(name: str, ok: bool, detail: str, fix: str | None = None, *, required: bool = True) -> dict:
    status = "ok" if ok else ("missing" if required else "warn")
    return {"name": name, "status": status, "required": required, "detail": detail, "fix": None if ok else fix}


def check_python(version_info=None) -> dict:
    version = tuple(version_info or sys.version_info)[:3]
    shown = ".".join(str(v) for v in version)
    return _check(
        "python", version[:2] >= MIN_PYTHON, f"Python {shown}",
        "install Python 3.12 and re-run `poetry install`",
    )


def _custom_home() -> bool:
    """True when `DOOR_HOME` puts the data somewhere other than the checkout."""
    from door.core import workspace

    return workspace.HOME != workspace.REPO_ROOT


def _data_file(path: Path, relative: str) -> str:
    """How a fix names a data file: ``profile/config.json``, or its real path under a custom home."""
    return str(path) if _custom_home() else relative


def check_profile(profile_dir: Path) -> dict:
    from door.core.profile_loader import ConfigError, load_config

    path = Path(profile_dir) / "config.json"
    try:
        load_config(path, check_paths=True)
    except FileNotFoundError:
        return _check("profile", False, f"{path} not found", "./door init")
    except ConfigError as exc:
        return _check("profile", False, "; ".join(exc.lines) or "invalid", f"fix {_data_file(path, 'profile/config.json')}")
    try:
        employers = companies.load(profile_dir)
    except companies.CompaniesError as exc:
        return _check("profile", False, "; ".join(str(exc).splitlines()), f"fix {_data_file(Path(profile_dir) / 'companies.json', 'profile/companies.json')}")
    return _check("profile", True, f"{path} is valid" + (f"; {len(employers)} employers" if employers else ""))


def check_latex(which=shutil.which, home: Path | None = None) -> dict:
    from door.core.installers import find_tectonic

    tectonic = find_tectonic(which=which, home=home)
    if tectonic:
        return _check("latex", True, f"tectonic: {tectonic}")
    found = which("xelatex")
    if found:
        return _check("latex", True, f"xelatex: {found}")
    return _check("latex", False, "no tectonic or xelatex found — needed by compile/prepare", _LATEX_FIX)


def check_claude_cli(which=shutil.which, home: Path | None = None) -> dict:
    found = installers.find_claude(which, home)
    check = _check(
        "claude CLI", bool(found),
        f"claude: {found}" if found else "no `claude` on PATH or in ~/.local/bin — needed by match/prepare/revise",
        "./door doctor --fix   (installs the claude CLI, no sudo)",
    )
    return {**check, "details": {"path": str(found)}} if found else check


_CLAUDE_LOGIN_FIX = "claude auth login (sign in with your Claude Pro/Max account)"


# The fields of `claude auth status --json` worth showing; never the organisation id.
_LOGIN_DETAIL_KEYS = ("loggedIn", "authMethod", "apiProvider", "configDirectory", "email", "orgName", "subscriptionType")


def check_claude_login(claude_path: str | None, run=subprocess.run, env: dict[str, str] | None = None) -> dict | None:
    """Is the `claude` CLI signed in to a plan? `claude auth status --json` is local and free.

    None when there is no CLI to ask (`check_claude_cli` already reports that).
    A CLI too old to have `auth status`, or one that hangs, gives a warning,
    not a failure: the login may well be fine. `env` is the environment
    The other door's `claude` calls run in (`claude_cli.env()`), so the check asks
    the plan they will use.
    """
    if not claude_path:
        return None
    why = ""
    try:
        proc = run([claude_path, "auth", "status", "--json"], capture_output=True, text=True, timeout=15, env=env,
                   stdin=subprocess.DEVNULL)
        # Signed out, `claude` exits 1 and still prints the status, so the exit code says nothing here.
        why = (proc.stderr or proc.stdout or f"exit {proc.returncode}, no output").strip()
        status = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        why = why or str(exc)
        status = None
    if not isinstance(status, dict) or "loggedIn" not in status:
        return _check(
            "claude login", False, f"could not read `claude auth status` ({why[:300]}) — check by running `claude`",
            "claude update (the CLI may be too old for auth status)", required=False,
        )
    details = {key: status[key] for key in _LOGIN_DETAIL_KEYS if key in status}
    # The folder The other door's own claude calls are signed in from (none: claude's default), so the app signs in there.
    config_dir = (env or {}).get("CLAUDE_CONFIG_DIR")
    if config_dir:
        details["doorConfigDir"] = config_dir
    if not status["loggedIn"]:
        check = _check("claude login", False, "not logged in — needed by match/prepare/revise", _CLAUDE_LOGIN_FIX)
        return {**check, "details": details}
    method = str(status.get("authMethod") or "")
    if "api" in method.lower() and "key" in method.lower():
        check = _check(
            "claude login", False,
            f"logged in with an API key ({method}); The other door runs on a Claude Pro/Max plan only",
            _CLAUDE_LOGIN_FIX,
        )
        return {**check, "details": details}
    who = [str(details[k]) for k in ("email", "subscriptionType") if details.get(k)]
    parts = [method or "ok", *who, *([config_dir] if config_dir else [])]
    return {**_check("claude login", True, f"logged in ({', '.join(parts)})"), "details": details}


_MCP_CONFIG = ".mcp.json"


def mcp_interpreter(repo_root: Path, platform: str = sys.platform) -> Path:
    """The interpreter `.mcp.json` should point at: the in-project venv's python."""
    repo_root = Path(repo_root)
    if platform == "win32":
        return repo_root / ".venv" / "Scripts" / "python.exe"
    return repo_root / ".venv" / "bin" / "python"


def mcp_server_env(repo_root: Path) -> dict[str, str]:
    """`.mcp.json`'s ``env`` for the server, a relative PYTHONPATH resolved against
    `repo_root` (Claude Code starts the server there); {} without a readable entry.

    The package lives in src/door/ and is never installed, so the entry puts
    src/ on PYTHONPATH.
    """
    repo_root = Path(repo_root)
    try:
        env = dict(json.loads((repo_root / _MCP_CONFIG).read_text(encoding="utf-8"))["mcpServers"]["door"].get("env") or {})
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
    if env.get("PYTHONPATH"):
        env["PYTHONPATH"] = os.pathsep.join(
            str(p if Path(p).is_absolute() else repo_root / p) for p in env["PYTHONPATH"].split(os.pathsep)
        )
    return env


def check_mcp_server(repo_root: Path, find_spec=importlib.util.find_spec, platform: str = sys.platform) -> dict:
    """Can Claude Code start the MCP server from `.mcp.json`?

    The entry runs the in-project venv's interpreter directly (no Poetry on
    PATH needed, which GUI-launched apps rarely have). It fails silently in
    Claude Code when that interpreter is missing (`poetry install` not run)
    or `.mcp.json` names an interpreter that does not exist here.
    """
    repo_root = Path(repo_root)
    config_path = repo_root / _MCP_CONFIG
    try:
        command = json.loads(config_path.read_text(encoding="utf-8"))["mcpServers"]["door"]["command"]
    except (OSError, ValueError, KeyError, TypeError):
        return _check("mcp server", False, f"{config_path} is missing or malformed", "git checkout .mcp.json", required=False)
    expected = mcp_interpreter(repo_root, platform)
    pythonpath = mcp_server_env(repo_root).get("PYTHONPATH", "").split(os.pathsep)
    if str(repo_root / "src") not in pythonpath:
        return _check(
            "mcp server", False, f"{config_path} does not put src/ on PYTHONPATH — the server cannot import door",
            "git checkout .mcp.json", required=False,
        )
    interpreter = Path(command) if Path(command).is_absolute() or "/" in command or "\\" in command else None
    if interpreter is None:
        found = bool(shutil.which(command))
        detail = f"`{command}` on PATH" if found else f"`{command}` is not on PATH — Claude Code cannot start the server"
        return _check("mcp server", found, detail, f"point .mcp.json's command at {expected}", required=False)
    if not interpreter.is_absolute():
        interpreter = repo_root / interpreter
    if not interpreter.exists():
        if interpreter.resolve() == expected.resolve():
            return _check("mcp server", False, f"{interpreter} not found — Claude Code cannot start the server", "poetry install", required=False)
        return _check(
            "mcp server", False, f"{interpreter} not found on this platform — Claude Code cannot start the server",
            f"set .mcp.json's command to {expected}", required=False,
        )
    if find_spec("mcp") is None:
        return _check("mcp server", False, "the `mcp` package is not installed", "poetry install", required=False)
    return _check("mcp server", True, f"{interpreter} (from {_MCP_CONFIG})", required=False)


def check_generated_mcp(find_spec=importlib.util.find_spec) -> dict:
    """Can the tailor's session start the server from the `.mcp.json` door generates for a custom
    `DOOR_HOME`? It names the running interpreter and the code's `src/`; nothing is written here."""
    from door.core import workspace

    entry = workspace.mcp_config_entry()["mcpServers"]["door"]
    if not Path(entry["command"]).exists():
        return _check("mcp server", False, f"{entry['command']} not found", "re-run ./scripts/setup.sh", required=False)
    if str(workspace.REPO_ROOT / "src") not in entry["env"]["PYTHONPATH"].split(os.pathsep):
        return _check("mcp server", False, "src/ is not on PYTHONPATH", "re-run ./scripts/setup.sh", required=False)
    if find_spec("mcp") is None:
        return _check("mcp server", False, "the `mcp` package is not installed", "poetry install", required=False)
    return _check("mcp server", True, f"{entry['command']} (generated in {workspace.HOME})", required=False)


MCP_PROBE_TIMEOUT_S = 30
_INITIALIZE = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "door-setup", "version": "1"}},
})


def mcp_server_argv(repo_root: Path, platform: str = sys.platform) -> list[str]:
    """The command Claude Code runs for the server: `.mcp.json`'s entry, or the
    in-project venv's python when that entry's interpreter does not exist here
    (Windows, where `setup` registers a local entry pointing at it)."""
    repo_root = Path(repo_root)
    args = ["-m", "door.mcp_server"]
    try:
        entry = json.loads((repo_root / _MCP_CONFIG).read_text(encoding="utf-8"))["mcpServers"]["door"]
        command, args = entry["command"], list(entry.get("args", args))
    except (OSError, ValueError, KeyError, TypeError):
        command = None
    if command and ("/" in command or "\\" in command):
        path = Path(command) if Path(command).is_absolute() else repo_root / command
        command = str(path) if path.exists() or platform != "win32" else None
    return [command or str(mcp_interpreter(repo_root, platform)), *args]


def probe_mcp_server(repo_root: Path, *, run=subprocess.run, platform: str = sys.platform, timeout: float = MCP_PROBE_TIMEOUT_S) -> dict:
    """Start the server the way Claude Code does and check it answers `initialize`.

    `check_mcp_server` only looks at files; this catches a server that is
    there but crashes on import (a half-finished `poetry install`).
    """
    repo_root = Path(repo_root)
    argv = mcp_server_argv(repo_root, platform)
    try:
        env = {**os.environ, **mcp_server_env(repo_root)}
        proc = run(argv, input=_INITIALIZE + "\n", capture_output=True, text=True, cwd=repo_root, env=env, timeout=timeout)
        reply = json.loads((proc.stdout or "").splitlines()[0]) if proc.stdout else {}
        ok = proc.returncode == 0 and "result" in reply
        detail = "answers on stdio" if ok else f"did not answer: {(proc.stderr or '').strip()[-200:] or f'exit {proc.returncode}'}"
    except subprocess.TimeoutExpired:
        ok, detail = False, f"no answer within {timeout:g}s"
    except (OSError, ValueError) as exc:
        ok, detail = False, f"could not start `{argv[0]}`: {exc}"
    return _check("mcp server", ok, detail, "re-run ./scripts/setup.sh (it reinstalls the Python packages)")


def check_dev_deps(find_spec=importlib.util.find_spec) -> dict:
    missing = [m for m in DEV_MODULES if find_spec(m) is None]
    return _check(
        "dev dependencies", not missing,
        "pytest, responses, genbadge installed" if not missing else f"missing: {', '.join(missing)} (only needed for ./scripts/run-test.sh)",
        "poetry install",
        required=False,
    )


def configured_sites(config: dict) -> list[str]:
    """The sites a run reads: every board of the profile's country, then the platforms of the followed
    employers (their ids are in *config* under the feed keys, as `run_checks` merges them in)."""
    feeds = [site for site, key in FEED_SITES.items() if config.get(key)]
    return list(dict.fromkeys([*sites.boards_for_location(config.get("location", "")), *feeds]))


def last_scrape_per_site(config: dict, jobs_dir: Path, now: datetime | None = None) -> list[dict]:
    """Each board's watermark from `jobs/scrape_state.json` (None = never scraped). Only boards have
    one: an employer's feed is read whole, what is new is what the history has not seen."""
    from door.core.freshness import _parse_dt, load_scrape_state

    now = now or datetime.now(timezone.utc)
    state = load_scrape_state(jobs_dir)
    rows = []
    for site in sites.boards_for_location(config.get("location", "")):
        raw = (state.get(site) or {}).get("last_success")
        when = _parse_dt(raw)
        age = round((now - when).total_seconds() / 3600, 1) if when else None
        rows.append({"site": site, "last_success": raw if when else None, "age_hours": age})
    return rows


def last_run(jobs_dir: Path) -> dict | None:
    """The newest `jobs/runs/<timestamp>.json`: when, ok/failed, what failed."""
    runs_dir = Path(jobs_dir) / "runs"
    if not runs_dir.is_dir():
        return None
    records = sorted(runs_dir.glob("*.json"))
    for path in reversed(records):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        failures = list(record.get("failures") or [])
        return {
            "started_at": record.get("started_at"),
            "outcome": "failed" if failures else "ok",
            "failures": failures,
            "new_above_threshold": len(record.get("new_above_threshold") or []),
        }
    return None


def run_history(jobs_dir: Path) -> dict[str, float]:
    """Average ``count`` per site over the last `HISTORY_RUNS` run records.

    Only the per-site entries of the ``search`` and ``collect`` blocks with ``outcome == "ok"`` count; unreadable records are skipped.
    """
    runs_dir = Path(jobs_dir) / "runs"
    if not runs_dir.is_dir():
        return {}
    counts: dict[str, list[int]] = {}
    for path in sorted(runs_dir.glob("*.json"))[-HISTORY_RUNS:]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            sites = runs.site_entries(record)
        except (OSError, ValueError, AttributeError):
            continue
        for entry in sites:
            if isinstance(entry, dict) and entry.get("outcome") == "ok" and isinstance(entry.get("count"), int):
                counts.setdefault(entry.get("site"), []).append(entry["count"])
    return {site: sum(v) / len(v) for site, v in counts.items()}


def assess_probe(result: ProbeResult, avg: float | None) -> tuple[str, str]:
    """Turn a probe result and the site's historic average into ``(status, detail)``.

    Only a clean fetch whose expected structure is missing is ``drift``; a
    wall or an unreachable site is ``warn`` (code cannot fix it).
    """
    reason = result.get("reason") or ""
    if result.get("robots") == "disallowed":
        return "warn", f"not probed: {reason}".rstrip(": ")
    if result.get("unreachable"):
        return "warn", f"unreachable: {reason}".rstrip(": ")
    if result.get("wall"):
        return "warn", f"login/bot wall: {reason}".rstrip(": ")
    if not result["structure_ok"]:
        return "drift", reason or "expected results structure not found"
    found = len(result["postings"])
    if avg is not None and found == 0 and avg >= MIN_AVG_FOR_ZERO_WARN:
        return "warn", f"0 results where runs average {avg:g}"
    if avg and found > HIGH_FACTOR * avg:
        return "warn", f"{found} results on page 1 where runs average {avg:g}"
    return "ok", f"{found} result(s) on page 1"


def _scraper_check(name: str, status: str, detail: str, fix: str | None, *, fixable: bool = False) -> dict:
    from door.core import sites

    site = name.removeprefix("scraper: ")
    return {
        "name": name, "status": status, "required": False, "detail": detail,
        "fix": None if status == "ok" else fix, "fixable": fixable,
        # the site in words ("The Hub"), for a list a person reads
        "details": {"site": site, "site_name": sites.source_name(site) or site},
    }


def check_unsure_sources(config: dict) -> dict:
    """The `unsure` sources (their terms forbid automated access) the user turned on, so they stay visible."""
    names = ", ".join(s["label"] for s in discovery_sources.on(config))
    return _check("terms: unsure sources on", True, names or "none")


def default_probe(site: str, config: dict, profile_dir: Path) -> ProbeResult | None:
    """Run the site's scraper ``probe`` (module from the site registry); any exception becomes an unreachable result."""
    import importlib

    try:
        from door.core.sites import SITES

        module = importlib.import_module(SITES[site].module)
        probe = getattr(module, "probe", None)
        if probe is None:
            return None
        return probe(config)
    except Exception as exc:  # noqa: BLE001 - a probe must never crash doctor
        return {"raw": "", "ext": "html", "postings": [], "structure_ok": False,
                "unreachable": True, "reason": f"{type(exc).__name__}: {exc}"}


def _save_raw(jobs_dir: Path, site: str, result: ProbeResult, now: datetime) -> Path:
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = Path(jobs_dir) / "drift" / site / f"{stamp}.{result.get('ext') or 'html'}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.get("raw") or "", encoding="utf-8")
    return path


def check_scrapers(
    config: dict, profile_dir: Path, jobs_dir: Path, *, probe=None, now: datetime | None = None
) -> list[dict]:
    """One ``scraper: <site>`` check per configured site, from its live probe.

    When robots.txt is obeyed (`http_client.OBEY_ROBOTS`), each detail ends with
    its verdict on the URL probed (issue #226).
    A site whose terms reserve it against scraping is never probed. On
    ``drift``/``warn`` the raw response is saved to
    ``jobs/drift/<site>/<timestamp>.<ext>``.
    """
    from door.core.sites import SITES

    now = now or datetime.now(timezone.utc)
    probe = probe or default_probe  # resolved late so tests can patch the default
    history = None
    checks = []
    for site in configured_sites(config):
        if site in SITES and SITES[site].verdict == "reserved":
            checks.append(_scraper_check(
                f"scraper: {site}", "warn", f"reserved by its terms ({SITES[site].terms_url}); never fetched",
                None,
            ))
            continue
        try:
            result = probe(site, config, profile_dir)
        except Exception as exc:  # noqa: BLE001
            result = {"raw": "", "ext": "html", "postings": [], "structure_ok": False,
                      "unreachable": True, "reason": f"{type(exc).__name__}: {exc}"}
        if result is None:
            continue
        if history is None:
            history = run_history(jobs_dir)
        status, detail = assess_probe(result, history.get(site))
        verdict = {"allowed": "allows", "disallowed": "disallows"}.get(result.get("robots", ""))
        if verdict and http_client.OBEY_ROBOTS:
            detail += f"; robots.txt {verdict} it"
        name = f"scraper: {site}"
        if status == "ok":
            checks.append(_scraper_check(name, status, detail, None))
            continue
        blocked = result.get("robots") == "disallowed"
        fixable = not (result.get("wall") or result.get("unreachable") or blocked)
        saved = _save_raw(jobs_dir, site, result, now) if (result.get("raw") or fixable) else None
        if saved:
            detail += f" (raw response: {saved})"
        if blocked:
            fix = f"the site no longer allows this request; open an issue (or unfollow its employers)"
        elif fixable:
            fix = "./door doctor --probe --fix   (offers to repair it)"
        else:
            fix = "usually transient; re-run doctor later"
        checks.append(_scraper_check(name, status, detail, fix, fixable=fixable))
    return checks


def _reaches(port: int) -> bool:
    import requests

    try:
        return requests.get(f"http://127.0.0.1:{port}/manifest.webmanifest", timeout=1).ok
    except requests.RequestException:
        return False


def _sleep_minutes(run=subprocess.run) -> int | None:
    """The Mac's idle sleep (`pmset -g`), in minutes; 0 = never, None = unknown or not a Mac."""
    if sys.platform != "darwin":
        return None
    try:
        out = run(["pmset", "-g"], capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "sleep" and parts[1].isdigit():
            return int(parts[1])
    return None


def check_serve_instances(reach=_reaches, sleep_minutes=_sleep_minutes) -> dict | None:
    """The `door serve` instances on this machine (#302): each answers? how many phones? does the Mac sleep?"""
    from door.core import instances, pairing

    found = instances.read()
    if not found:
        return None
    parts, fine = [], True
    for home, entry in found.items():
        up = reach(entry["port"])
        fine = fine and up
        phones = len(pairing.devices(Path(home)))
        parts.append(f"{entry.get('name') or home} on port {entry['port']}: "
                     f"{'answering' if up else 'not answering'}, {phones} phone{'' if phones == 1 else 's'} paired")
    sleep = sleep_minutes()
    if sleep:
        fine = False
        parts.append(f"this Mac sleeps after {sleep} minutes, and a phone cannot reach a sleeping Mac")
    return _check("phone server", fine, "; ".join(parts),
                  "start it (`./door serve`, or `serve install-agent`); System Settings → Energy: prevent sleep",
                  required=False)


def run_checks(
    profile_dir: Path,
    jobs_dir: Path,
    *,
    which=shutil.which,
    find_spec=importlib.util.find_spec,
    now: datetime | None = None,
    run=subprocess.run,
    probe=None,
    probe_sites: bool = False,
    repo_root: Path | None = None,
) -> dict:
    """Every check, plus the last run and last scrapes.

    The local checks are instant and offline. The ``scraper: <site>`` checks
    hit every configured site,
    so they only run with ``probe_sites=True`` (`doctor --probe`, or `doctor --probe --fix`
    when it looks for scrapers to fix); ``probe(site, config, profile_dir)``
    is then the probe to use (default: the real network one; tests inject a
    stub). ``drift`` and ``warn`` statuses are non-fatal.

    Returns:
        ``{"ok": <every required check passed>, "checks": [...],
        "last_run": {...} | None, "last_scrape": [{"site", "last_success",
        "age_hours"}, ...]}``.
    """
    from door.core.profile_loader import ConfigError, load_config

    try:
        config = load_config(Path(profile_dir) / "config.json")
    except (FileNotFoundError, ConfigError):
        config = {}
    try:  # the probes read the followed employers like a scrape does
        config = {**config, **companies.feed_config(profile_dir)}
    except companies.CompaniesError:
        pass  # `check_profile` reports a broken companies.json
    from door.core import workspace

    if repo_root is None:
        repo_root = workspace.REPO_ROOT

    checks = [
        check_python(),
        check_profile(profile_dir),
        check_latex(which=which),
        check_claude_cli(which=which),
        check_claude_login(installers.find_claude(which), run=run, env=claude_cli.env(profile_dir=profile_dir)),
        check_generated_mcp(find_spec=find_spec) if _custom_home() else check_mcp_server(repo_root, find_spec=find_spec),
        # the test tools mean something only in a checkout, not in a packaged app
        check_dev_deps(find_spec=find_spec) if workspace.is_checkout() else None,
        check_serve_instances(),
        check_unsure_sources(config),
    ]
    checks = [c for c in checks if c is not None]
    if probe_sites:
        checks.extend(check_scrapers(config, profile_dir, jobs_dir, probe=probe, now=now))

    data = migrations.recheck()  # not the start-up answer: the sidebar line follows what is on disk now
    return {
        "ok": not any(c["status"] == "missing" for c in checks),
        "home": str(workspace.HOME),
        # What the upgrade of the data folders found (#56): the app puts a line at the sidebar's foot for a refusal.
        "data": data or {"state": "ok", "message": ""},
        "checks": checks,
        "last_run": last_run(jobs_dir),
        "last_scrape": last_scrape_per_site(config, jobs_dir, now=now),
    }
