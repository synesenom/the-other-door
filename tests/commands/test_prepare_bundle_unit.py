"""The packaged app's bundle (app/scripts/bundle-python.sh, .ps1) carries every agent file the code reads: the tailor's,
the matcher, the stylist and every model prompt (#639: an installed app's Prepare failed on a missing reviewer.md)."""

from paths import REPO_ROOT

_SCRIPTS = {
    REPO_ROOT / "app" / "scripts" / "bundle-python.sh": '"$REPO"/.claude/agents/*.md',
    REPO_ROOT / "app" / "scripts" / "bundle-python.ps1": ".claude\\agents\\*.md",
}


def test_every_agent_file_is_bundled():
    for script, copies_them_all in _SCRIPTS.items():
        assert copies_them_all in script.read_text(encoding="utf-8"), f"{script.name} does not copy every agent file"
