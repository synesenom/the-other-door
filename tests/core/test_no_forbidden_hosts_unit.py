"""Guard: The other door reads LinkedIn (employer discovery) logged out, from one module only, and never
drives a captured session.

LinkedIn is employer discovery (docs/job-sites.md), read logged out: no login, no cookies,
no stored session, no account. So its host (and its guest endpoint) may be named only by
its scraper and the site registry (terms links); nothing under
`src/door/` or `.claude/` may handle a login or a captured session.
"""

from paths import PACKAGE_DIR, REPO_ROOT

_HOSTS = ("linkedin.com", "jobs-guest")
_HOST_FILES = {
    "src/door/scrapers/discovery/linkedin.py",
    "src/door/core/sites.py",
}
# Nothing that stores or replays a session, or logs in.
_SESSION_WORDS = (
    "storage_state", "li_at", "jsessionid", "cookies.json", "login_url", "logged_in_marker",
    "needs_login", "launch_persistent_context", "add_cookies",
)
_ROOTS = (PACKAGE_DIR, REPO_ROOT / ".claude")
_SUFFIXES = {".py", ".md", ".toml", ".json", ".txt"}
_WORKTREES = REPO_ROOT / ".claude" / "worktrees"   # other checkouts (gitignored), each scanned in its own run


def _texts():
    for root in _ROOTS:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in _SUFFIXES and "__pycache__" not in path.parts \
                    and not path.is_relative_to(_WORKTREES):
                yield str(path.relative_to(REPO_ROOT)), path.read_text(encoding="utf-8").lower()


def test_only_the_linkedin_module_and_the_registry_name_its_hosts():
    offenders = [
        f"{rel}: {word}" for rel, text in _texts() for word in _HOSTS if word in text and rel not in _HOST_FILES
    ]
    assert offenders == []


def test_nothing_handles_a_login_or_a_captured_session():
    offenders = [f"{rel}: {word}" for rel, text in _texts() for word in _SESSION_WORDS if word in text]
    assert offenders == []


def test_no_login_command_or_tool_exists():
    from door import cli, mcp_server

    assert "login" not in cli.cli.commands
    assert "login" not in mcp_server.CLI_COMMAND_TOOLS


def test_only_the_drive_module_names_googles_hosts():
    """Google Drive sync (#265) talks to Google from `core/drive.py` alone."""
    offenders = [
        rel
        for rel, text in _texts()
        for host in ("googleapis.com", "accounts.google.com")
        if host in text and rel != "src/door/core/drive.py"
    ]
    assert offenders == []
