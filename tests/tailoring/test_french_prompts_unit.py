"""The LaTeX that tailor.md's French rules (#389) tell the tailor to write passes the tex guard."""

import re

from door.tailoring import tex_guard
from tests.paths import REPO_ROOT

AGENTS = REPO_ROOT / ".claude" / "agents"


def _french_section() -> str:
    text = (AGENTS / "tailor.md").read_text(encoding="utf-8")
    language = text.split("\n## Language", 1)[1].split("\n## ", 1)[0]
    assert "\n### French" in language, "tailor.md's Language section lost its French subsection"
    return language.split("\n### French", 1)[1].split("\n### ", 1)[0]


def test_the_latex_the_french_rules_tell_the_tailor_to_write_passes_the_tex_guard():
    snippets = re.findall(r"`([^`]*\\[^`]*)`", _french_section())
    assert snippets, "tailor.md's French rules name no LaTeX to check"
    for snippet in snippets:
        assert tex_guard.unsafe(snippet) == [], snippet


