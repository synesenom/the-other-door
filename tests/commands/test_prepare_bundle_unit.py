"""The packaged app's bundle (app/scripts/bundle-python.sh, .ps1) carries every agent file the pipeline reads
(#639: an installed app's Prepare failed on a missing reviewer.md)."""

import re

from door.commands import prepare
from paths import REPO_ROOT

_SCRIPTS = (REPO_ROOT / "app" / "scripts" / "bundle-python.sh", REPO_ROOT / "app" / "scripts" / "bundle-python.ps1")


def _bundled_agents(script) -> set[str]:
    return set(re.findall(r"([a-z_-]+)\.md", script.read_text(encoding="utf-8")))


def test_every_agent_the_tailor_and_the_scorer_read_is_bundled():
    needed = {*prepare._TAILOR_AGENTS, "matcher"}
    for script in _SCRIPTS:
        assert needed <= _bundled_agents(script), f"{script.name} leaves out {sorted(needed - _bundled_agents(script))}"
