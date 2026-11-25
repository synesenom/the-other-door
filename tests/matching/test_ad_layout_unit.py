"""A well-scored ad written once as Markdown by Haiku, kept only when its words are the ad's own, in order."""

import json

import pytest

from door.core import claude_cli
from door.matching import ad_layout

DESC = "About the role\nWe build forecasts.\nYou bring\nLine-manage the team\n: Drive 1:1s.\n• SQL\n\nApply today."
MD = "## About the role\n\nWe build forecasts.\n\n## You bring\n\n- Line-manage the team: Drive 1:1s.\n- SQL\n\nApply today."


def test_markdown_with_the_ads_words_in_order_is_kept():
    assert ad_layout.same_words(DESC, MD)


@pytest.mark.parametrize("md", [
    MD.replace("We build forecasts.", "We build great forecasts."),   # a word added
    MD.replace("- SQL\n", ""),                                         # a word dropped
    MD.replace("Drive 1:1s.", "1:1s. Drive"),                          # words out of order
    MD.replace("forecasts", "forcasts"),                               # a word changed
])
def test_markdown_that_changes_the_ads_words_is_refused(md):
    assert not ad_layout.same_words(DESC, md)


def _posting(tmp_path, **extra):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"id": "x", "description": DESC, **extra}))
    return path


def test_lay_out_sends_the_ad_and_stores_its_markdown(tmp_path, monkeypatch):
    seen = {}

    def ask(agent, text, **kw):
        seen.update(agent=agent, text=text, feature=kw["feature"])
        return {"markdown": MD}

    monkeypatch.setattr(claude_cli, "ask", ask)
    path = _posting(tmp_path)

    assert ad_layout.lay_out(path) is True
    assert seen == {"agent": "ad-layout", "text": DESC, "feature": "ad_layout"}
    stored = json.loads(path.read_text())
    assert stored["description"] == MD and stored["formatted"] is True


def test_an_answer_that_changes_the_words_leaves_the_ad_as_it_was(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_cli, "ask", lambda *a, **k: {"markdown": MD.replace("SQL", "SQL and Spark")})
    path = _posting(tmp_path)
    before = path.read_text()
    assert ad_layout.lay_out(path) is False
    assert path.read_text() == before  # plain text: the next run asks again


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
    assert path.read_text() == before
