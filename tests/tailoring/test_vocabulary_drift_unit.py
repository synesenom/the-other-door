"""The closed vocabulary lives in three places (#188): `html_guard.CLASSES`, the tailor's prompt and the templates'
header comments. A class named in either of the last two that the guard refuses would print as a refused body."""

import re

from door.tailoring import html_guard
from paths import REPO_ROOT

_CLASS = re.compile(r'class="([^"]*)"')


def _classes(text: str) -> set[str]:
    return {token for value in _CLASS.findall(text) for token in value.split()}


def _tailor_blocks() -> str:
    text = (REPO_ROOT / ".claude" / "agents" / "tailor.md").read_text(encoding="utf-8")
    return text.split("## Building blocks", 1)[1].split("\n## ", 1)[0]


def _header_comment(name: str) -> str:
    text = (REPO_ROOT / "profile.example" / name).read_text(encoding="utf-8")
    return re.search(r"<!--(.*?)-->", text, re.S).group(1)


def test_every_class_the_tailor_is_told_to_write_is_one_the_guard_accepts():
    named = _classes(_tailor_blocks())
    assert {"cv-header", "contact", "entry"} <= named  # the reading found the blocks
    assert named - html_guard.CLASSES == set()


def test_every_class_a_templates_header_comment_names_is_one_the_guard_accepts():
    for name in ("cv.template.html", "cover-letter.template.html"):
        named = _classes(_header_comment(name))
        assert named, name
        assert named - html_guard.CLASSES - {"photo"} == set(), name
