"""A posting whose title looks like markup is printed as the text it is, by the real process (#549)."""

import json

import pytest

from cli_world import build_world

pytestmark = pytest.mark.cli_journeys

MARKUP = "[link=https://evil.example]x[/link]"


def test_a_posting_titled_with_markup_prints_literally():
    world = build_world("mette")
    template = next((world.home / "jobs" / "postings").rglob("*.json"))
    posting = json.loads(template.read_text(encoding="utf-8"))
    posting.update(id=posting["id"] + "-markup", title=MARKUP + "\x1b]0;pwn\x07", score=0.99)
    (template.parent / f"{posting['id']}.json").write_text(json.dumps(posting), encoding="utf-8")

    for args in (("jobs", "list"), ("jobs", "show", "link evil")):
        code, out, err = world.door(*args)
        assert code == 0, f"{out}\n{err}"
        assert MARKUP in out, out
        assert "\x1b]" not in out and "\x07" not in out
