"""`door.core.scraper_fix`: gated branch-and-PR repair of a drifted scraper (issue #178).

git, gh, `claude -p` and the test/probe gate are all injected, so the whole
flow (including a fixer that writes a broken patch) runs offline.
"""

import os
import subprocess
from datetime import datetime

import pytest

from door.core import lock, scraper_fix
from door.core.scraper_fix import ScraperFixerError, fix_scraper

NOW = datetime(2026, 10, 8, 9, 30)
BRANCH = "fix/scraper-jobindex-2026-10-08-0930"


class FakeRun:
    """Stands in for subprocess.run: records argv, answers git/gh from a few knobs."""

    def __init__(self, dirty="", branch="main", push_rc=0, gh_rc=0, gh_missing=False, push_missing=False):
        self.calls: list[list[str]] = []
        self.dirty = dirty
        self.branch = branch
        self.push_rc, self.gh_rc = push_rc, gh_rc
        self.gh_missing, self.push_missing = gh_missing, push_missing
        self.current = branch
        self.deleted: list[str] = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        out, rc = "", 0
        if argv[:3] == ["git", "status", "--porcelain"]:
            out = self.dirty
        elif argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            out = self.current + "\n"
        elif argv[:3] == ["git", "checkout", "-b"]:
            self.current = argv[3]
        elif argv[:2] == ["git", "checkout"]:
            self.current = argv[2]
        elif argv[:3] == ["git", "branch", "-D"]:
            self.deleted.append(argv[3])
        elif argv[:2] == ["git", "push"]:
            if self.push_missing:
                raise FileNotFoundError("git")
            rc = self.push_rc
        elif argv[0] == "gh":
            if self.gh_missing:
                raise FileNotFoundError("gh")
            rc, out = self.gh_rc, "https://github.com/o/r/pull/7\n"
        return subprocess.CompletedProcess(argv, rc, stdout=out, stderr="")

    def ran(self, *prefix):
        return [c for c in self.calls if c[: len(prefix)] == list(prefix)]


@pytest.fixture
def env(tmp_path):
    jobs = tmp_path / "jobs"
    (jobs / "drift" / "jobindex").mkdir(parents=True)
    (jobs / "drift" / "jobindex" / "20261008T000000Z.html").write_text("<html/>")
    return jobs, tmp_path / "repo", tmp_path / "profile"


def _fixer(run, porcelain=" M src/door/scrapers/boards/jobindex.py\n?? tests/scrapers/boards/fixtures/jobindex/\n M tests/scrapers/boards/test_jobindex_unit.py\n"):
    seen = []

    def fixer(site, raw_path, timeout_s):
        seen.append((site, raw_path))
        run.dirty = porcelain  # what `git status` shows once the agent has edited
        return "Renamed the results block key."

    fixer.seen = seen
    return fixer


def _go(env, run, fixer, gate=lambda *a: (True, "ok"), **kw):
    jobs, repo, profile = env
    return fix_scraper("jobindex", jobs_dir=jobs, repo_root=repo, profile_dir=profile,
                       run=run, fixer=fixer, gate=gate, now=NOW, **kw)


def _assert_restored(run):
    assert run.current == "main"
    assert run.deleted == [BRANCH]
    assert run.ran("git", "reset", "--hard") and run.ran("git", "clean", "-fd")
    assert not run.ran("git", "commit") and not run.ran("git", "push")


def test_refuses_a_dirty_working_tree(env):
    run = FakeRun(dirty=" M src/door/core/doctor.py\n")
    out = _go(env, run, _fixer(run))
    assert out["outcome"] == "refused" and "uncommitted" in out["error"]
    assert not run.ran("git", "checkout")


def test_refuses_while_a_run_holds_the_ledger_lock(env, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def held(jobs_dir, purpose):
        raise lock.LockHeldError("a run is in progress; try again when it has finished")
        yield

    monkeypatch.setattr(scraper_fix, "ledger_lock", held)
    run = FakeRun()
    fixer = _fixer(run)
    out = _go(env, run, fixer)
    assert out["outcome"] == "refused" and "run is in progress" in out["error"]
    assert fixer.seen == [] and run.calls == []


def test_refuses_when_there_is_nothing_to_fix(env):
    run = FakeRun()
    assert _go(env, run, _fixer(run), check={"status": "ok"})["outcome"] == "refused"
    assert _go(env, run, _fixer(run), check={"status": "warn", "fixable": False})["outcome"] == "refused"
    jobs, repo, profile = env
    out = fix_scraper("lever", jobs_dir=jobs, repo_root=repo, profile_dir=profile, run=run)
    assert out["outcome"] == "refused" and "doctor" in out["error"]
    assert run.calls == []


def test_happy_path_commits_only_the_scraper_paths_pushes_and_opens_a_pr(env):
    run = FakeRun()
    fixer = _fixer(run)
    out = _go(env, run, fixer, check={"status": "drift", "fixable": True})
    assert out == {"site": "jobindex", "outcome": "pr", "branch": BRANCH, "url": "https://github.com/o/r/pull/7"}
    assert fixer.seen[0][0] == "jobindex" and fixer.seen[0][1].name == "20261008T000000Z.html"
    assert run.ran("git", "checkout", "-b", BRANCH)
    [add] = run.ran("git", "add")
    assert add == ["git", "add", "--", "src/door/scrapers/boards/jobindex.py", "tests/scrapers/boards/fixtures/jobindex/", "tests/scrapers/boards/test_jobindex_unit.py"]
    [commit] = run.ran("git", "commit")
    assert "Renamed the results block key." in commit[-1]
    assert run.ran("git", "push", "-u", "origin", BRANCH)
    [gh] = run.ran("gh", "pr", "create")
    assert "Renamed the results block key." in gh[gh.index("--body") + 1]
    assert run.current == "main" and run.deleted == []  # back on the original branch, fix branch kept


@pytest.mark.parametrize("kw", [{"push_rc": 1}, {"push_missing": True}])
def test_push_failure_falls_back_to_a_local_branch(env, kw):
    run = FakeRun(**kw)
    out = _go(env, run, _fixer(run))
    assert out["outcome"] == "local_branch" and out["branch"] == BRANCH
    assert out["commands"][0] == f"git push -u origin {BRANCH}"
    assert any(c.startswith("gh pr create") for c in out["commands"])
    assert run.ran("git", "commit") and run.current == "main" and run.deleted == []


@pytest.mark.parametrize("kw", [{"gh_missing": True}, {"gh_rc": 1}])
def test_gh_failure_falls_back_to_a_local_branch(env, kw):
    run = FakeRun(**kw)
    out = _go(env, run, _fixer(run))
    assert out["outcome"] == "local_branch" and out["commands"][0].startswith("gh pr create")
    assert run.ran("git", "push")


def test_broken_patch_is_never_committed(env):
    """The fixer 'fixes' the scraper but the tests/probe gate fails: discard everything."""
    run = FakeRun()
    out = _go(env, run, _fixer(run), gate=lambda *a: (False, "offline tests failed"))
    assert out["outcome"] == "gate_failed" and "offline tests failed" in out["detail"]
    _assert_restored(run)


def test_fixer_error_restores_the_branch(env):
    run = FakeRun()

    def fixer(site, raw_path, timeout_s):
        raise ScraperFixerError("timed out after 1200s")

    out = _go(env, run, fixer)
    assert out["outcome"] == "fixer_failed" and "timed out" in out["error"]
    _assert_restored(run)


def test_fixer_touching_other_files_fails_without_running_the_gate(env):
    run = FakeRun()
    called = []
    out = _go(env, run, _fixer(run, porcelain=" M src/door/core/doctor.py\n M src/door/scrapers/boards/jobindex.py\n"),
              gate=lambda *a: called.append(1) or (True, "ok"))
    assert out["outcome"] == "gate_failed" and "src/door/core/doctor.py" in out["detail"]
    assert called == []
    _assert_restored(run)


def test_fixer_changing_nothing_fails(env):
    run = FakeRun()
    out = _go(env, run, _fixer(run, porcelain=""))
    assert out["outcome"] == "gate_failed"
    _assert_restored(run)


def test_unexpected_exception_still_restores_the_original_branch(env):
    run = FakeRun()

    def fixer(site, raw_path, timeout_s):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        _go(env, run, fixer)
    _assert_restored(run)


def test_allowed_paths():
    ok = scraper_fix._allowed
    assert ok("lever", "src/door/scrapers/feeds/lever.py")
    assert ok("lever", "tests/scrapers/feeds/test_lever_scrape.py")
    assert ok("lever", "tests/scrapers/feeds/fixtures/lever/postings.json")
    assert not ok("lever", "src/door/scrapers/feeds/greenhouse.py") and not ok("lever", "src/door/core/doctor.py")
    assert not ok("lever", "tests/scrapers/feeds/fixtures/lever_other/x.json")
    assert not ok("lever", "tests/scrapers/feeds/test_greenhouse_scrape.py")
    assert not ok("lever", "tests/scrapers/feeds/sub/test_lever_scrape.py")
    # the old layouts are not the scraper's any more: flat, and the region packages before it
    assert not ok("lever", "src/door/scrapers/lever.py")
    assert not ok("lever", "tests/scrapers/test_lever_scrape.py")
    assert not ok("lever", "src/door/scrapers/worldwide/lever.py")
    assert not ok("lever", "tests/scrapers/worldwide/test_lever_scrape.py")
    # each kind's scraper, tests and fixtures sit in the folders of its kind
    assert ok("jobindex", "src/door/scrapers/boards/jobindex.py")
    assert ok("jobindex", "tests/scrapers/boards/test_jobindex_unit.py")
    assert ok("jobindex", "tests/scrapers/boards/fixtures/jobindex/search_page1.html")
    assert not ok("jobindex", "tests/scrapers/test_jobindex_unit.py")
    assert not ok("lever", "tests/test_lever_scrape.py") and not ok("lever", "tests/fixtures/lever/x.json")


def test_the_agent_prompt_and_fresh_probe_use_the_site_registry(tmp_path):
    assert "src/door/scrapers/feeds/lever.py" in scraper_fix._fixer_prompt("lever", tmp_path / "raw.json")
    assert "SITES[sys.argv[1]].module" in scraper_fix._PROBE_SNIPPET
    assert "feed_config" in scraper_fix._PROBE_SNIPPET   # the probe sees the followed employers


def test_default_gate_requires_green_tests_and_a_healthy_probe(tmp_path):
    def make(test_rc, probe_stdout, probe_rc=0):
        def run(argv, **kw):
            if "pytest" in argv:
                return subprocess.CompletedProcess(argv, test_rc, stdout="1 failed\n", stderr="")
            return subprocess.CompletedProcess(argv, probe_rc, stdout=probe_stdout, stderr="")
        return run

    healthy = '{"structure_ok": true, "count": 12, "reason": "", "wall": false, "unreachable": false}\n'
    drift = '{"structure_ok": false, "count": 0, "reason": "no block", "wall": false, "unreachable": false}\n'
    gate = scraper_fix.default_gate
    assert gate("jobindex", tmp_path, tmp_path, run=make(0, healthy))[0] is True
    assert gate("jobindex", tmp_path, tmp_path, run=make(1, healthy))[0] is False
    ok, detail = gate("jobindex", tmp_path, tmp_path, run=make(0, drift))
    assert ok is False and "no block" in detail
    assert gate("jobindex", tmp_path, tmp_path, run=make(0, "null\n"))[0] is False
    zero = '{"structure_ok": true, "count": 0, "reason": "", "wall": false, "unreachable": false}\n'
    assert gate("jobindex", tmp_path, tmp_path, run=make(0, zero))[0] is False


def test_scraper_path_is_under_src():
    """The fixer may only commit this file, so it must be the real one (src/door/...)."""
    assert scraper_fix._scraper_path("jobindex") == "src/door/scrapers/boards/jobindex.py"


def test_default_gate_probe_finds_the_package_in_src(tmp_path, monkeypatch):
    """The probe is `python -c` from the repo root, where `import door` needs src/ on PYTHONPATH."""
    monkeypatch.setenv("PYTHONPATH", "/opt/extra")
    seen = {}

    def run(argv, **kw):
        if "pytest" not in argv:
            seen.update(kw)
        out = '{"structure_ok": true, "count": 1, "reason": "", "wall": false, "unreachable": false}\n'
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    assert scraper_fix.default_gate("jobindex", tmp_path, tmp_path, run=run)[0] is True
    assert seen["env"]["PYTHONPATH"].split(os.pathsep) == [str(tmp_path / "src"), "/opt/extra"]
    assert seen["env"]["PATH"] == os.environ["PATH"]


def test_run_scraper_fixer_uses_claude_print_mode_only(monkeypatch, tmp_path):
    seen = {}

    def fake(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        return subprocess.CompletedProcess(argv, 0, stdout="summary\n", stderr="")

    monkeypatch.setattr(scraper_fix.subprocess, "run", fake)
    assert scraper_fix._run_scraper_fixer("jobindex", tmp_path / "raw.html", 5, tmp_path) == "summary"
    assert seen["argv"][:2] == ["claude", "-p"] and "--allowedTools" in seen["argv"]
    assert seen["kw"]["cwd"] == tmp_path and seen["kw"]["timeout"] == 5

    monkeypatch.setattr(scraper_fix.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 2, stdout="", stderr="bad"))
    with pytest.raises(ScraperFixerError, match="bad"):
        scraper_fix._run_scraper_fixer("jobindex", tmp_path / "raw.html", 5)

    def missing(*a, **k):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(scraper_fix.subprocess, "run", missing)
    with pytest.raises(ScraperFixerError, match="claude"):
        scraper_fix._run_scraper_fixer("jobindex", tmp_path / "raw.html", 5)

    def slow(*a, **k):
        raise subprocess.TimeoutExpired("claude", 5)

    monkeypatch.setattr(scraper_fix.subprocess, "run", slow)
    with pytest.raises(ScraperFixerError, match="timed out"):
        scraper_fix._run_scraper_fixer("jobindex", tmp_path / "raw.html", 5)


def test_status_lists_untracked_files_individually(env):
    """A brand-new fixtures dir must not collapse to `tests/scrapers/<region>/fixtures/` (which is outside the allowed paths)."""
    run = FakeRun()
    _go(env, run, _fixer(run))
    assert ["git", "status", "--porcelain", "--untracked-files=all"] in run.calls


def test_run_scraper_fixer_uses_the_resolved_claude_path(monkeypatch, tmp_path):
    from door.core import installers

    seen = {}

    def fake(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(installers, "find_claude", lambda *a, **k: "/x/claude")
    monkeypatch.setattr(scraper_fix.subprocess, "run", fake)
    scraper_fix._run_scraper_fixer("jobindex", tmp_path / "raw.html", 5, tmp_path)
    assert seen["argv"][0] == "/x/claude"


def test_refuses_outside_a_checkout(env, monkeypatch):
    # A packaged app has no git, no tests and no branch to open a pull request from (#223).
    from door.core import workspace

    monkeypatch.setattr(workspace, "is_checkout", lambda: False)
    run = FakeRun()
    out = _go(env, run, _fixer(run))
    assert out["outcome"] == "refused" and "checkout" in out["error"]
    assert not run.ran("git", "status")


# --------------------------------------------------------------------------- #
# the fixer reads an untrusted page: pytest only, edits scoped, sandboxed (#441)
# --------------------------------------------------------------------------- #

def _fixer_argv(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(scraper_fix.subprocess, "run", lambda argv, **kw: seen.update(argv=argv) or subprocess.CompletedProcess(argv, 0, stdout="ok", stderr=""))
    scraper_fix._run_scraper_fixer("jobindex", tmp_path / "raw.html", 5, tmp_path)
    return seen["argv"]


def test_fixer_may_run_only_pytest(monkeypatch, tmp_path):
    argv = _fixer_argv(monkeypatch, tmp_path)
    allowed = argv[argv.index("--allowedTools") + 1].split(",")
    bash = [t for t in allowed if t.startswith("Bash")]
    assert bash == ["Bash(poetry run pytest:*)"]


def test_fixer_edits_only_the_scrapers_and_their_tests(monkeypatch, tmp_path):
    argv = _fixer_argv(monkeypatch, tmp_path)
    allowed = argv[argv.index("--allowedTools") + 1].split(",")
    assert "Write" not in allowed and "Edit" not in allowed
    root = "/" + tmp_path.absolute().as_posix()
    assert sorted(t for t in allowed if t.startswith(("Edit", "Write"))) == [
        f"Edit({root}/src/door/scrapers/**)", f"Edit({root}/tests/scrapers/**)"]


def test_fixer_runs_its_commands_in_the_sandbox_without_secrets(monkeypatch, tmp_path):
    import json

    argv = _fixer_argv(monkeypatch, tmp_path)
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert settings["sandbox"]["enabled"] is True
    assert settings["sandbox"]["allowUnsandboxedCommands"] is False
    assert "~/.ssh" in settings["sandbox"]["filesystem"]["denyRead"]


def test_fixer_reads_only_the_checkout_and_the_saved_response(monkeypatch, tmp_path):
    argv = _fixer_argv(monkeypatch, tmp_path)
    allowed = argv[argv.index("--allowedTools") + 1].split(",")
    root = "/" + tmp_path.absolute().as_posix()
    assert "Read" not in allowed   # a bare Read allows any file
    assert sorted(t for t in allowed if t.startswith("Read")) == [f"Read({root}/**)", f"Read({root}/raw.html)"]
