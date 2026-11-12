"""The project's Claude Code settings keep a conversation in this repo out of the usual secret
folders (#441): Read deny rules, and the same folders unreadable to sandboxed commands."""

import json

from paths import REPO_ROOT

_SECRETS = ("~/.ssh", "~/.aws", "~/.gnupg", "~/.config/door")


def _settings():
    return json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))


def test_reads_of_the_secret_folders_are_denied():
    deny = _settings()["permissions"]["deny"]
    for folder in _SECRETS:
        assert f"Read({folder}/**)" in deny


def test_commands_run_in_the_sandbox_without_the_secret_folders():
    sandbox = _settings()["sandbox"]
    assert sandbox["enabled"] is True
    for folder in _SECRETS:
        assert folder in sandbox["filesystem"]["denyRead"]


def test_no_deny_rule_covers_a_folder_a_checkout_lives_in():
    """A deny beats every allow: denying ~/Documents would lock out a repo cloned there."""
    settings = _settings()
    for rule in settings["permissions"]["deny"] + settings["sandbox"]["filesystem"]["denyRead"]:
        assert not any(name in rule for name in ("Documents", "Downloads", "Desktop", "~/**", "Read(~/)"))
