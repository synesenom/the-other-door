"""The packaged app's bundle (app/scripts/bundle-python.sh, .ps1) carries every agent file the code reads, a list
`tests/core/test_prompts_unit.py` checks against `src/door` (#639: an installed app's Prepare failed on a missing reviewer.md)."""

from paths import REPO_ROOT


def test_each_bundle_script_copies_its_listed_agents():
    sh = (REPO_ROOT / "app" / "scripts" / "bundle-python.sh").read_text(encoding="utf-8")
    ps1 = (REPO_ROOT / "app" / "scripts" / "bundle-python.ps1").read_text(encoding="utf-8")
    assert '"$REPO/.claude/agents/$a.md"' in sh
    assert ".claude\\agents\\$Agent.md" in ps1
