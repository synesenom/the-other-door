"""The HTML that tailor.md's rules tell the tailor to write passes the guard (#389, #146), and the rules name the
whole vocabulary."""

import re

from door.tailoring import html_guard
from tests.paths import REPO_ROOT

AGENTS = REPO_ROOT / ".claude" / "agents"


def _tailor() -> str:
    return (AGENTS / "tailor.md").read_text(encoding="utf-8")


def _french_section() -> str:
    text = _tailor()
    language = text.split("\n## Language", 1)[1].split("\n## ", 1)[0]
    assert "\n### French" in language, "tailor.md's Language section lost its French subsection"
    return language.split("\n### French", 1)[1].split("\n### ", 1)[0]


def test_the_html_the_french_rules_tell_the_tailor_to_write_passes_the_guard():
    snippets = re.findall(r"`([^`]*<[^`]*)`", _french_section())
    assert snippets, "tailor.md's French rules name no HTML to check"
    for snippet in snippets:
        assert html_guard.unsafe(snippet) == [], snippet


def test_the_building_blocks_in_tailor_md_pass_the_guard():
    blocks = re.findall(r"^```\n(.*?)^```", _tailor().split("## Building blocks", 1)[1].split("\n## ", 1)[0],
                        re.S | re.M)
    assert len(blocks) == 2, "tailor.md shows one CV and one letter block"
    for block in blocks:
        assert html_guard.unsafe(block) == [], block


def test_tailor_md_names_every_tag_and_class_the_guard_allows():
    text = _tailor()
    for tag in sorted(html_guard.TAGS):
        assert f"`{tag}`" in text or f"<{tag}" in text, tag
    for name in sorted(html_guard.CLASSES):
        assert name in text, name
    for token in ("<<photo>>", "<<company>>", "<<title>>", "<<date>>"):
        assert token in text, token
