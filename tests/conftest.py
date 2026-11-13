"""Fixtures shared by every test.

The repo root and tests/ are on sys.path through `pythonpath` in pyproject.toml.
"""

import pytest

from cli_utils import CaptureReporter
from door.commands import _common as common
from door.core import progress, sites
from door.matching import language
from door.scrapers import http_client, robots


@pytest.fixture(autouse=True)
def _no_follow_ai(request, monkeypatch):
    """`follow`'s Haiku fallback never reaches the `claude` CLI from a test; tests that want an answer patch this."""
    from door.core import careers_ai

    if request.module.__name__.endswith("test_careers_ai_unit"):
        return  # that module fakes `claude_cli.ask` underneath
    monkeypatch.setattr(careers_ai, "ask_careers_url", lambda *a, **k: None)


_WIKIDATA_TESTS = ("test_wikidata_unit", "test_follow_employer_site_unit")


@pytest.fixture(autouse=True)
def _no_wikidata(request, monkeypatch):
    """`follow`'s website lookup (Wikidata, #566) finds nothing in a test; its own tests serve saved answers."""
    from door.core import wikidata

    if request.module.__name__.endswith(_WIKIDATA_TESTS) or request.node.get_closest_marker("live"):
        return
    monkeypatch.setattr(wikidata.Lookup, "employer", lambda self, session, name: (None, None))


@pytest.fixture(autouse=True)
def _no_salary_search(request, monkeypatch):
    """`prepare`'s salary estimate (#624) never reaches the `claude` CLI from a test; the salary
    tests fake `claude_cli.ask` underneath and keep it."""
    from door.commands import prepare as prepare_cmd

    if request.module.__name__.endswith("test_salary_cli"):
        return
    monkeypatch.setattr(prepare_cmd, "_estimate_salary", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _claude_cli_present(monkeypatch):
    """`prepare` refuses to start without the `claude` CLI (#138). Tests
    fake the tailor run, so pretend it is installed; the guard's own tests
    override this."""
    monkeypatch.setattr(common, "_claude_available", lambda: True)


@pytest.fixture(autouse=True)
def _no_real_claude_lookup(monkeypatch, tmp_path_factory):
    """A test never sees the developer's real `claude` (PATH or ~/.local/bin): the runtime
    lookup finds nothing (the callers fall back to the bare name) unless a test passes its own
    `which`/`home` or patches `installers.find_claude` itself."""
    import shutil

    from door.core import installers

    real = installers.find_claude
    real_which = shutil.which
    empty_home = tmp_path_factory.mktemp("nohome")

    def find_claude(which=real_which, home=None):
        if which is real_which:
            return None
        return real(which, home if home is not None else empty_home)

    monkeypatch.setattr(installers, "find_claude", find_claude)


@pytest.fixture(autouse=True)
def _no_real_network(request, monkeypatch):
    """No offline test may reach the network: a request nobody mocked (a red test, a forgotten
    fake) fails at once instead of falling through to a real site. `responses` replaces this
    while a test mocks HTTP; `live` tests opt out."""
    if request.node.get_closest_marker("live"):
        return
    import requests.adapters

    def refuse(self, request, **kwargs):
        raise AssertionError(f"offline test tried to reach the network: {request.method} {request.url}")

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", refuse)


_REAL_BOARDS_FOR_LOCATION = sites.boards_for_location


@pytest.fixture(autouse=True)
def _no_real_jobs_dir(tmp_path_factory, monkeypatch):
    """No test reads or writes the repo's own `jobs/`: a command called without `jobs_dir` lands
    in a temp dir (taking the lock, or reading postings, would move the user's day folders)."""
    from door.core import workspace

    monkeypatch.setattr(workspace, "JOBS_DIR", tmp_path_factory.mktemp("jobs"))


@pytest.fixture(autouse=True)
def _one_board(monkeypatch):
    """`search` reads every board of the profile's country; a test reads Jobindex alone, so a fake for
    it is all a test needs. A test of the country rule uses `country_boards`."""
    monkeypatch.setattr(sites, "boards_for_location", lambda location: ["jobindex"])


@pytest.fixture
def country_boards(monkeypatch):
    """The real `sites.boards_for_location`: every board serving the profile's country."""
    monkeypatch.setattr(sites, "boards_for_location", _REAL_BOARDS_FOR_LOCATION)


@pytest.fixture(autouse=True)
def _no_drive_sync(tmp_path, monkeypatch):
    """No test reads this computer's Drive connection, opens a browser for Google, or syncs on a
    lock: `drive.json` lives in a temp dir (never connected), the lock hooks do nothing and
    `webbrowser.open` fails; no test sees the sync notes an earlier one left. A test of the sync
    itself uses `enable_sync_hooks`."""
    import webbrowser

    from door.core import drive, lock, sync

    sync.drain_notes()

    monkeypatch.setattr(drive, "_BASE", tmp_path / "drive-config")
    monkeypatch.setattr(drive, "CLIENT_ID", "")  # the real client never reaches a test
    monkeypatch.setattr(drive, "CLIENT_SECRET", "")
    monkeypatch.setattr(lock, "pre_acquire_hook", lambda purpose, jobs_dir: None)
    monkeypatch.setattr(lock, "post_release_hook", lambda purpose, jobs_dir: None)

    def refuse(*args, **kwargs):
        raise AssertionError("offline test tried to open a browser")

    monkeypatch.setattr(webbrowser, "open", refuse)


@pytest.fixture(autouse=True)
def _no_start_upgrade(monkeypatch):
    """The upgrade of the data folders at the start of the CLI and the server (#56) never touches a test's folders by
    itself, and no test sees the state another left; a test of the upgrade calls `migrations` itself."""
    from door.core import migrations

    monkeypatch.setattr(migrations, "run_at_start", lambda: None)
    monkeypatch.setattr(migrations, "_state", None)


@pytest.fixture
def enable_sync_hooks(monkeypatch):
    """Put the real Drive sync hooks back on the ledger lock (for tests with a fake Drive)."""
    from door.core import lock

    monkeypatch.setattr(lock, "pre_acquire_hook", lock._default_pre)
    monkeypatch.setattr(lock, "post_release_hook", lock._default_post)


@pytest.fixture(autouse=True)
def _no_title_translation(monkeypatch):
    """`scrape` translates non-English titles with `claude -p`; no test may
    reach the real CLI, so every call fails softly (no `title_en`). Tests of
    the translation itself pass their own runner."""
    monkeypatch.setattr(language, "_run_claude", lambda argv, stdin: None)


@pytest.fixture(autouse=True)
def _robots_allow_all(request, monkeypatch):
    """Every `PoliteSession` request reads robots.txt first (#226). Tests mock
    their pages, not each host's robots.txt, so it allows everything unless a
    test is marked `real_robots` (then `responses` serves robots.txt too)."""
    if request.node.get_closest_marker("real_robots") or request.node.get_closest_marker("live"):
        return
    monkeypatch.setattr(http_client.PoliteSession, "_fetch_robots", lambda self, origin: robots.Rules.allow_all())


@pytest.fixture
def obey_robots(monkeypatch):
    """robots.txt gates requests (`http_client.OBEY_ROBOTS`, off by default):
    for the tests of what The other door does when it is on."""
    monkeypatch.setattr(http_client, "OBEY_ROBOTS", True)


@pytest.fixture
def progress_events():
    """The list of `Progress` events reported while the test runs."""
    with progress.activate(CaptureReporter()) as cap:
        yield cap.events


@pytest.fixture(autouse=True)
def _stdio_runs():
    """`door serve` turns on background runs for the process (#302); every test starts over stdio's rules."""
    from door import mcp_server

    mcp_server._runs_reset()
    yield
    mcp_server._runs_reset()
