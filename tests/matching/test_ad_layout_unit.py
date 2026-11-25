"""A well-scored ad written once as Markdown from the model's verified line numbers, its words its own."""

import json

import pytest

from door.core import claude_cli
from door.matching import ad_layout

DESC = "About the role\nWe build forecasts.\nYou bring\n- Python\n- SQL\n\nApply today."


def test_verified_keeps_only_integers_in_range_and_drops_a_line_named_twice():
    answer = {"headings": [1, 3, 99, 0, "2", 1.5, True, 4], "bullets": [4, 5, 5, -1]}
    assert ad_layout.verified(answer, 6) == {"headings": [1, 3], "bullets": [5], "joins": []}


@pytest.mark.parametrize("answer", [None, [], {"headings": "1"}, {}])
def test_verified_survives_a_malformed_answer(answer):
    assert ad_layout.verified(answer, 5) == {"headings": [], "bullets": [], "joins": []}


def test_the_ad_becomes_markdown_with_its_own_words():
    md = ad_layout.markdown(DESC, {"headings": [1, 3], "bullets": [4, 5]})
    assert md == "## About the role\n\nWe build forecasts.\n\n## You bring\n\n- Python\n- SQL\n\nApply today."


def test_a_line_named_neither_stays_a_paragraph():
    assert ad_layout.markdown("One\nTwo", {"headings": [], "bullets": []}) == "One\n\nTwo"


def _posting(tmp_path, **extra):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"id": "x", "description": DESC, **extra}))
    return path


def test_lay_out_sends_numbered_lines_and_stores_the_ad_as_markdown(tmp_path, monkeypatch):
    seen = {}

    def ask(agent, text, **kw):
        seen.update(agent=agent, text=text, feature=kw["feature"])
        return {"headings": [1, 3, 40], "bullets": [4, 5, 3]}

    monkeypatch.setattr(claude_cli, "ask", ask)
    path = _posting(tmp_path)

    assert ad_layout.lay_out(path) is True
    assert seen["agent"] == "ad-layout" and seen["feature"] == "ad_layout"
    assert seen["text"].splitlines()[:2] == ["1: About the role", "2: We build forecasts."]
    stored = json.loads(path.read_text())
    assert stored["description"] == "## About the role\n\nWe build forecasts.\n\nYou bring\n\n- Python\n- SQL\n\nApply today."
    assert stored["formatted"] is True


def test_an_ad_already_written_as_markdown_makes_no_call(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_cli, "ask", lambda *a, **k: pytest.fail("asked"))
    assert ad_layout.lay_out(_posting(tmp_path, formatted=True)) is False


def test_a_failed_call_leaves_the_posting_as_it_was(tmp_path, monkeypatch):
    def fail(*a, **k):
        raise claude_cli.ClaudeError("down")

    monkeypatch.setattr(claude_cli, "ask", fail)
    path = _posting(tmp_path)
    before = path.read_text()
    assert ad_layout.lay_out(path) is False
    assert path.read_text() == before  # the raw text: the next run asks again


def test_a_line_that_continues_the_one_before_is_joined_to_it():
    # a list item's label and its text, split onto two lines by the page the ad was read from
    desc = "What you'll do\nLine-manage and grow the team\n: Drive 1:1s and recruitment.\nOwn the architecture\n— lead the vision."
    md = ad_layout.markdown(desc, {"headings": [1], "bullets": [2, 3, 4], "joins": [3, 5]})
    assert md == "## What you'll do\n\n- Line-manage and grow the team: Drive 1:1s and recruitment.\n- Own the architecture — lead the vision."


def test_verified_keeps_joins_after_the_first_line_only():
    assert ad_layout.verified({"headings": [], "bullets": [], "joins": [1, 2, 9, "3"]}, 5)["joins"] == [2]
