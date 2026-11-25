"""The layout of a well-scored ad: verified line numbers, stored with the description's hash."""

import json

import pytest

from door.core import claude_cli
from door.matching import ad_layout

DESC = "About the role\nWe build forecasts.\nYou bring\n- Python\n- SQL\n\nApply today."


def test_verified_keeps_only_integers_in_range_and_drops_a_line_named_twice():
    answer = {"headings": [1, 3, 99, 0, "2", 1.5, True, 4], "bullets": [4, 5, 5, -1]}
    assert ad_layout.verified(answer, 6) == {"headings": [1, 3], "bullets": [5]}


@pytest.mark.parametrize("answer", [None, [], {"headings": "1"}, {}])
def test_verified_survives_a_malformed_answer(answer):
    assert ad_layout.verified(answer, 5) == {"headings": [], "bullets": []}


def test_without_a_layout_every_non_empty_line_is_a_paragraph():
    blocks = ad_layout.blocks(DESC, None)
    assert [b["kind"] for b in blocks] == ["paragraph"] * 6
    assert blocks[3]["text"] == "- Python"


def test_a_layout_marks_headings_and_bullets_and_strips_the_marker():
    layout = {"headings": [1, 3], "bullets": [4, 5], "sha256": ad_layout.description_hash(DESC)}
    blocks = ad_layout.blocks(DESC, layout)
    assert [b["kind"] for b in blocks] == ["heading", "paragraph", "heading", "bullet", "bullet", "paragraph"]
    assert blocks[3]["text"] == "Python"


def test_a_layout_of_another_description_is_ignored():
    layout = {"headings": [1], "bullets": [], "sha256": ad_layout.description_hash("old text")}
    assert {b["kind"] for b in ad_layout.blocks(DESC, layout)} == {"paragraph"}


def _posting(tmp_path, **extra):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"id": "x", "description": DESC, **extra}))
    return path


def test_lay_out_sends_numbered_lines_and_stores_the_verified_layout(tmp_path, monkeypatch):
    seen = {}

    def ask(agent, text, **kw):
        seen.update(agent=agent, text=text, feature=kw["feature"])
        return {"headings": [1, 3, 40], "bullets": [4, 5, 3]}

    monkeypatch.setattr(claude_cli, "ask", ask)
    path = _posting(tmp_path)

    assert ad_layout.lay_out(path) is True
    assert seen["agent"] == "ad-layout" and seen["feature"] == "ad_layout"
    assert seen["text"].splitlines()[:2] == ["1: About the role", "2: We build forecasts."]
    stored = json.loads(path.read_text())["layout"]
    assert stored == {"headings": [1], "bullets": [4, 5], "sha256": ad_layout.description_hash(DESC)}


def test_a_posting_with_a_layout_for_its_description_makes_no_call(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_cli, "ask", lambda *a, **k: pytest.fail("asked"))
    path = _posting(tmp_path, layout={"headings": [], "bullets": [], "sha256": ad_layout.description_hash(DESC)})
    assert ad_layout.lay_out(path) is False


def test_a_layout_of_an_older_description_is_made_again(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_cli, "ask", lambda *a, **k: {"headings": [1], "bullets": []})
    path = _posting(tmp_path, layout={"headings": [2], "bullets": [], "sha256": "stale"})
    assert ad_layout.lay_out(path) is True
    assert json.loads(path.read_text())["layout"]["headings"] == [1]


def test_a_failed_call_leaves_the_posting_as_it_was(tmp_path, monkeypatch):
    def fail(*a, **k):
        raise claude_cli.ClaudeError("down")

    monkeypatch.setattr(claude_cli, "ask", fail)
    path = _posting(tmp_path)
    before = path.read_text()
    assert ad_layout.lay_out(path) is False
    assert path.read_text() == before
