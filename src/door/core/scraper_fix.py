"""Gated, branch-and-PR repair of a drifted scraper (issue #178).

`doctor` flags a scraper whose live site no longer has the structure it parses
(``scraper: <site>`` -> ``drift``) and saves the raw response under
``jobs/drift/<site>/``. `fix_scraper` hands that response to the headless
``scraper-fixer`` agent (`claude -p`, never an API key) on a fresh
``fix/scraper-<site>-<date>`` branch, then lets nothing through unless the
offline test suite is green AND a probe in a fresh process reports the site
healthy with at least one posting. A passing fix is committed (scraper, its
tests and fixtures only), pushed and opened as a PR through `gh`; when push or
`gh` is unavailable the local branch and the commands to finish by hand are
returned instead. A failing fix is discarded: the original branch is checked
out again, the fix branch deleted, the tree left clean.

Every subprocess goes through an injectable seam (`run`, `fixer`, `gate`) so
tests exercise the whole flow, including a fixer that writes a broken patch,
without git, a network or `claude`.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from door.core import claude_cli, installers, usage, workspace
from door.core.lock import LockHeldError, ledger_lock
from door.core.sites import ALL_SITES

# The fixer reads a live page (untrusted, #441): its only command is pytest, it edits only the
# scrapers and their tests (`_fixer_tools`; an `Edit(path)` rule covers every file-writing tool),
# and its commands, the tests it writes included, run in Claude Code's sandbox (`_FIXER_SETTINGS`):
# writes only in the checkout, no network, the usual secret folders unreadable.
_SCRAPER_FIXER_ALLOWED_TOOLS = ("Bash(poetry run pytest:*)",)
_FIXER_EDITABLE = ("src/door/scrapers", "tests/scrapers")
_SECRET_DIRS = ("~/.ssh", "~/.aws", "~/.gnupg", "~/.netrc", "~/.docker", "~/.kube", "~/.config/door",
                "~/.config/gh", "~/.config/gcloud", "~/.claude")  # not ~/Documents: a checkout often lives there
_FIXER_SETTINGS = {
    "sandbox": {
        "enabled": True,
        "allowUnsandboxedCommands": False,
        "filesystem": {"denyRead": list(_SECRET_DIRS)},
        "network": {"allowedDomains": []},
    },
}
_DEFAULT_FIXER_TIMEOUT_S = 20 * 60
_GATE_TEST_TIMEOUT_S = 15 * 60
_GATE_PROBE_TIMEOUT_S = 120
_FIXABLE_STATUSES = ("drift", "warn")


class ScraperFixerError(RuntimeError):
    """The `claude -p` scraper-fixer run failed (non-zero exit, timeout, or no `claude`)."""


def latest_raw(jobs_dir: Path, site: str) -> Path | None:
    """The newest raw response `doctor` saved for *site* under ``jobs/drift/<site>/``."""
    folder = Path(jobs_dir) / "drift" / site
    files = sorted(p for p in folder.glob("*") if p.is_file()) if folder.is_dir() else []
    return files[-1] if files else None


def _run_scraper_fixer(site: str, raw_path: Path, timeout_s: float | None = _DEFAULT_FIXER_TIMEOUT_S,
                       repo_root: Path | None = None) -> str:
    """Drive the scraper-fixer agent for *site* via the `claude` CLI; returns its summary.

    Shells out to ``claude -p "<prompt>" --allowedTools ...`` from the repo root
    so ``.claude/agents/scraper-fixer.md`` is found. This is the seam tests
    replace. Only the plan's `claude -p` is used; there is no API key anywhere.

    Raises:
        ScraperFixerError: non-zero exit, timeout, or the `claude` binary is missing.
    """
    prompt = _fixer_prompt(site, raw_path)
    try:
        result = subprocess.run(
            [installers.find_claude() or "claude", "-p", prompt, "--allowedTools", ",".join(_fixer_tools(repo_root, raw_path)),
             "--settings", json.dumps(_FIXER_SETTINGS), *claude_cli.STREAM_ARGS],
            capture_output=True, text=True, cwd=repo_root, timeout=timeout_s, env=claude_cli.env(),
        )
    except subprocess.TimeoutExpired:
        raise ScraperFixerError(f"timed out after {timeout_s:.0f}s") from None
    except (FileNotFoundError, OSError) as exc:
        raise ScraperFixerError(f"could not invoke `claude` CLI: {exc}") from None
    envelope, limits = claude_cli.read_stream(result.stdout)
    usage.record("scraper_fix", envelope, limits=limits)
    if result.returncode != 0:
        detail = (result.stderr or "").strip() or f"exit code {result.returncode}"
        raise ScraperFixerError(f"claude exited {result.returncode}: {detail}")
    try:
        summary = claude_cli.envelope_result(envelope or result.stdout)
    except claude_cli.ClaudeError:
        summary = result.stdout  # only a summary: the fixer's work is its edits, judged by the gate
    return str(summary or "").strip()


def _fixer_tools(repo_root: Path | None, raw_path: Path | None = None) -> list[str]:
    """`_SCRAPER_FIXER_ALLOWED_TOOLS` plus `Read` of the checkout and the saved response, and an
    `Edit` rule for each `_FIXER_EDITABLE` folder. Never a bare `Read`: that reads any file."""
    root = Path(repo_root or workspace.REPO_ROOT).absolute()
    reads = [f"Read(/{root.as_posix()}/**)"]
    if raw_path is not None:
        reads.append(f"Read(/{Path(raw_path).absolute().as_posix()})")
    return [*_SCRAPER_FIXER_ALLOWED_TOOLS, *reads, *(f"Edit(/{(root / sub).as_posix()}/**)" for sub in _FIXER_EDITABLE)]


def _scraper_path(site: str) -> str:
    """The scraper's file, e.g. ``src/door/scrapers/boards/jobindex.py`` (from the site registry)."""
    from door.core.sites import SITES

    return "src/" + SITES[site].module.replace(".", "/") + ".py"


def _fixer_prompt(site: str, raw_path: Path) -> str:
    return (
        f"Invoke the scraper-fixer agent for site {site!r}. The saved drift response is {raw_path}. "
        f"Repair {_scraper_path(site)} test-first per .claude/agents/scraper-fixer.md, "
        "then finish with a short plain-text summary of what changed and why."
    )


_PROBE_SNIPPET = (
    "import importlib, json, sys\n"
    "from pathlib import Path\n"
    "from door.core.profile_loader import load_config\n"
    "from door.core import companies\n"
    "from door.core.sites import SITES\n"
    "cfg = load_config(Path(sys.argv[2]) / 'config.json')\n"
    "cfg.update(companies.feed_config(Path(sys.argv[2])))\n"
    "r = importlib.import_module(SITES[sys.argv[1]].module).probe(cfg)\n"
    "print(json.dumps(None if r is None else {'structure_ok': r['structure_ok'], 'count': len(r['postings']),"
    " 'reason': r.get('reason', ''), 'wall': bool(r.get('wall')), 'unreachable': bool(r.get('unreachable'))}))\n"
)


def default_gate(site: str, repo_root: Path, profile_dir: Path, run=subprocess.run) -> tuple[bool, str]:
    """The offline suite must pass and a fresh-process probe must report *site* healthy.

    A fresh process (not an import in this one) so the edited module is what
    runs. Uses ``pytest -m "not live"`` rather than ./scripts/run-test.sh so the
    tracked coverage badge is never rewritten.
    """
    try:
        tests = run(["poetry", "run", "pytest", "-m", "not live", "-q"], cwd=repo_root,
                    capture_output=True, text=True, timeout=_GATE_TEST_TIMEOUT_S)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return False, f"could not run the test suite: {exc}"
    if tests.returncode != 0:
        tail = "\n".join((tests.stdout or "").strip().splitlines()[-5:])
        return False, f"offline tests failed:\n{tail}"
    try:
        # `python -c` puts only the current directory on sys.path; the package is src/door/.
        pythonpath = os.pathsep.join(p for p in (str(Path(repo_root) / "src"), os.environ.get("PYTHONPATH")) if p)
        probe = run(["poetry", "run", "python", "-c", _PROBE_SNIPPET, site, str(profile_dir)], cwd=repo_root,
                    capture_output=True, text=True, timeout=_GATE_PROBE_TIMEOUT_S,
                    env={**os.environ, "PYTHONPATH": pythonpath})
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return False, f"could not run the probe: {exc}"
    lines = (probe.stdout or "").strip().splitlines()
    try:
        outcome = json.loads(lines[-1]) if probe.returncode == 0 and lines else None
    except ValueError:
        outcome = None
    if not outcome:
        return False, f"the fresh probe returned nothing usable (exit {probe.returncode})"
    if not outcome["structure_ok"] or outcome["count"] < 1:
        why = outcome.get("reason") or f"{outcome['count']} postings"
        return False, f"the fresh probe is still not ok: {why}"
    return True, f"tests pass; probe ok with {outcome['count']} posting(s)"


def _allowed(site: str, path: str) -> bool:
    """Only the site's scraper, its tests and its fixtures (beside the tests, as the package lays them out)."""
    from door.core.sites import SITES

    tests_dir = "tests/" + SITES[site].module.split(".", 1)[1].rsplit(".", 1)[0].replace(".", "/") + "/"
    test_name = path[len(tests_dir):] if path.startswith(tests_dir) else ""
    return (
        path == _scraper_path(site)
        or (test_name.startswith(f"test_{site}_") and test_name.endswith(".py") and "/" not in test_name)
        or path.startswith(f"{tests_dir}fixtures/{site}/")
    )


def _changed_paths(porcelain: str) -> list[str]:
    paths = []
    for line in porcelain.splitlines():
        if len(line) > 3:
            path = line[3:].strip().strip('"')
            paths.append(path.split(" -> ")[-1])
    return paths


def _git(run, repo_root: Path, *args: str):
    return run(["git", *args], cwd=repo_root, capture_output=True, text=True)


def _restore(run, repo_root: Path, original: str, branch: str) -> None:
    """Drop the fix attempt: discard changes, return to *original*, delete *branch*."""
    _git(run, repo_root, "reset", "--hard", "HEAD")
    _git(run, repo_root, "clean", "-fd")
    _git(run, repo_root, "checkout", original)
    _git(run, repo_root, "branch", "-D", branch)


def fix_scraper(
    site: str,
    *,
    jobs_dir: Path,
    repo_root: Path,
    profile_dir: Path,
    check: dict | None = None,
    run=subprocess.run,
    fixer=None,
    gate=default_gate,
    now: datetime | None = None,
) -> dict:
    """Repair *site* on a branch, gate the fix, and open a PR. Never prints.

    Returns:
        ``{"site", "outcome", ...}`` with outcome ``"pr"`` (``branch``,
        ``url``), ``"local_branch"`` (``branch``, ``commands`` to finish by
        hand), ``"gate_failed"`` (``detail``), ``"fixer_failed"`` (``error``)
        or ``"refused"`` (``error``: dirty tree, a run in progress, nothing to
        fix). Anything but ``"pr"``/``"local_branch"`` leaves the original
        branch checked out with a clean tree and no fix branch.
    """
    repo_root, jobs_dir = Path(repo_root), Path(jobs_dir)
    if fixer is None:
        def fixer(site, raw_path, timeout_s):  # noqa: E306 - the real `claude -p` run, rooted at the repo
            return _run_scraper_fixer(site, raw_path, timeout_s, repo_root)
    out = {"site": site}

    def refuse(message: str) -> dict:
        return {**out, "outcome": "refused", "error": message}

    if not workspace.is_checkout():
        return refuse("repairing a scraper needs The other door's git checkout (with its tests); the packaged app has none")
    if site not in ALL_SITES:
        return refuse(f"unknown site {site!r}")
    if check is not None and not (check.get("status") in _FIXABLE_STATUSES and check.get("fixable", True)):
        return refuse(f"scraper: {site} is not a code problem (status {check.get('status')!r}) — nothing to fix")
    raw_path = latest_raw(jobs_dir, site)
    if raw_path is None:
        return refuse(f"no saved response under jobs/drift/{site}/ — run `doctor` first")
    try:
        with ledger_lock(jobs_dir, "setup"):
            pass  # only a check: the fixer edits code, not the ledgers
    except LockHeldError as exc:
        return refuse(str(exc))

    try:
        status = _git(run, repo_root, "status", "--porcelain")
        if status.returncode != 0:
            return refuse(f"git status failed: {(status.stderr or '').strip()}")
        if (status.stdout or "").strip():
            return refuse("the working tree has uncommitted changes — commit or stash them first")
        head = _git(run, repo_root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    except (FileNotFoundError, OSError) as exc:
        return refuse(f"git is not available: {exc}")
    original = head if head and head != "HEAD" else _git(run, repo_root, "rev-parse", "HEAD").stdout.strip()
    base = head if head and head != "HEAD" else "main"

    stamp = (now or datetime.now()).strftime("%Y-%m-%d-%H%M")
    branch = f"fix/scraper-{site}-{stamp}"
    created = _git(run, repo_root, "checkout", "-b", branch)
    if created.returncode != 0:
        return refuse(f"could not create {branch}: {(created.stderr or '').strip()}")

    keep_branch = False
    try:
        try:
            summary = fixer(site, raw_path, _DEFAULT_FIXER_TIMEOUT_S)
        except ScraperFixerError as exc:
            return {**out, "outcome": "fixer_failed", "error": str(exc)}

        # --untracked-files=all: a new fixtures dir must list its files, not collapse to its parent
        changed = _changed_paths(_git(run, repo_root, "status", "--porcelain", "--untracked-files=all").stdout or "")
        stray = [p for p in changed if not _allowed(site, p)]
        if stray:
            return {**out, "outcome": "gate_failed", "detail": f"the fixer touched files outside the {site} scraper: {', '.join(stray)}"}
        if not changed:
            return {**out, "outcome": "gate_failed", "detail": "the fixer changed nothing"}

        passed, detail = gate(site, repo_root, profile_dir, run)
        if not passed:
            return {**out, "outcome": "gate_failed", "detail": detail}

        _git(run, repo_root, "add", "--", *changed)
        message = f"fix: {site} scraper for a changed site structure (doctor drift)\n\n{summary}".rstrip()
        committed = _git(run, repo_root, "commit", "-m", message)
        if committed.returncode != 0:
            return {**out, "outcome": "gate_failed", "detail": f"git commit failed: {(committed.stderr or '').strip()}"}
        keep_branch = True

        push_cmd = f"git push -u origin {branch}"
        pr_cmd = f"gh pr create --base {base} --head {branch} --fill"
        try:
            pushed = _git(run, repo_root, "push", "-u", "origin", branch)
            pushed_ok = pushed.returncode == 0
        except (FileNotFoundError, OSError):
            pushed_ok = False
        if not pushed_ok:
            return {**out, "outcome": "local_branch", "branch": branch, "commands": [push_cmd, pr_cmd]}
        try:
            pr = run(
                ["gh", "pr", "create", "--base", base, "--head", branch,
                 "--title", f"fix: {site} scraper for a changed site structure",
                 "--body", f"Found by `doctor` (scraper drift). Gated by the offline suite and a fresh probe.\n\n{summary}"],
                cwd=repo_root, capture_output=True, text=True,
            )
        except (FileNotFoundError, OSError):
            return {**out, "outcome": "local_branch", "branch": branch, "commands": [pr_cmd]}
        if pr.returncode != 0:
            return {**out, "outcome": "local_branch", "branch": branch, "commands": [pr_cmd]}
        lines = (pr.stdout or "").strip().splitlines()
        return {**out, "outcome": "pr", "branch": branch, "url": lines[-1] if lines else ""}
    finally:
        if keep_branch:
            _git(run, repo_root, "checkout", original)
        else:
            _restore(run, repo_root, original, branch)
