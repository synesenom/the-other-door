"""The Haiku question behind `follow`'s last resort. `claude_cli.ask` is faked."""

import pytest

from door.core import careers_ai, claude_cli


def test_the_answer_url_is_read():
    assert careers_ai.parse_url({"careers_url": " https://hk.dk/job "}) == "https://hk.dk/job"
    assert careers_ai.parse_url({"careers_url": None}) is None
    assert careers_ai.parse_url({"careers_url": "hk.dk/job"}) is None
    assert careers_ai.parse_url("nonsense") is None


def test_one_question_with_web_search_on_the_plan(monkeypatch):
    seen = {}

    def ask(system, text, **kw):
        seen.update(system=system, text=text, **kw)
        return {"careers_url": "https://hk.dk/job"}

    monkeypatch.setattr(claude_cli, "ask", ask)
    assert careers_ai.ask_careers_url("HK", "Advokatsekretær", "Copenhagen") == "https://hk.dk/job"
    assert seen["model"] == "haiku" and seen["allowed_tools"] == ("WebSearch",) and seen["schema"]
    assert "HK" in seen["text"] and "Advokatsekretær" in seen["text"] and "Copenhagen" in seen["text"]


def test_a_failed_call_is_no_answer(monkeypatch):
    def ask(*a, **k):
        raise claude_cli.ClaudeError("boom")

    monkeypatch.setattr(claude_cli, "ask", ask)
    assert careers_ai.ask_careers_url("HK", None, "") is None
