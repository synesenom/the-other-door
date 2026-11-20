"""The closed vocabulary lives in three places (#188): `html_guard.CLASSES`, the tailor's prompt and the templates'
header comments. A class named in either of the last two that the guard refuses would print as a refused body."""

import re

from door.core import claude_cli
from door.core import cv_read
from door.render import html_guard
from paths import REPO_ROOT

_CLASS = re.compile(r'class="([^"]*)"')


def _classes(text: str) -> set[str]:
    return {token for value in _CLASS.findall(text) for token in value.split()}


def _tailor_blocks() -> str:
    text = (claude_cli.PROMPTS_DIR / "tailor.md").read_text(encoding="utf-8")
    return text.split("## Building blocks", 1)[1].split("\n## ", 1)[0]


def _header_comment(name: str) -> str:
    text = (REPO_ROOT / "profile.example" / name).read_text(encoding="utf-8")
    return re.search(r"<!--(.*?)-->", text, re.S).group(1)


def test_every_class_the_tailor_is_told_to_write_is_one_the_guard_accepts():
    named = _classes(_tailor_blocks())
    assert {"cv-header", "contact", "entry"} <= named  # the reading found the blocks
    assert named - html_guard.CLASSES - html_guard.KIND_CLASSES == set()


def test_every_class_a_templates_header_comment_names_is_one_the_guard_accepts():
    for name in ("cv.template.html", "cover-letter.template.html"):
        named = _classes(_header_comment(name))
        assert named, name
        assert named - html_guard.CLASSES - html_guard.KIND_CLASSES - {"photo"} == set(), name


KINDS = set(cv_read.CONTACT_KINDS)


def test_the_tailor_is_told_the_tagline_and_every_contact_kind():
    named = _classes(_tailor_blocks())
    assert {"tagline"} | KINDS <= named


def test_the_tailor_is_told_the_entry_parts_and_every_level_class():
    named = _classes(_tailor_blocks())
    assert {"role", "org", "dates", "place", "sep", "level", "level-1", "level-2", "level-3", "level-4",
            "level-5"} <= named


def test_the_tailor_is_told_what_overflow_and_sparse_mean():
    text = (claude_cli.PROMPTS_DIR / "tailor.md").read_text(encoding="utf-8")
    assert "`overflow`" in text and "`sparse`" in text and "never invent" in text


def _text(*parts: str) -> str:
    return (REPO_ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def test_the_tailor_and_the_stylist_are_told_every_section_kind_class():
    for text in (_tailor_blocks(), (claude_cli.PROMPTS_DIR / "stylist.md").read_text(encoding="utf-8")):
        assert html_guard.KIND_CLASSES <= _named_kinds(text)


def _named_kinds(text: str) -> set[str]:
    return {c for c in html_guard.KIND_CLASSES if c in text}


def test_the_cv_templates_header_comment_names_every_section_kind_class():
    assert html_guard.KIND_CLASSES <= _named_kinds(_header_comment("cv.template.html"))


def test_the_revise_prompt_tells_to_give_a_heading_without_one_its_kind_class():
    assert "kind-" in claude_cli.prompt("reviser")
    assert html_guard.KIND_CLASSES <= _named_kinds(claude_cli.prompt("reviser"))
