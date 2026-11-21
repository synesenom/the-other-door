"""Unit tests for scripts/correct_evidence.py: the typed turns of the transcripts, and which quoted corrections are real."""

import importlib.util
import json

from paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("correct_evidence", REPO_ROOT / "scripts" / "correct_evidence.py")
ce = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ce)


def _line(role, content, session="s1", at="2026-01-01T00:00:00Z", **flags):
    return json.dumps({"type": role, "message": {"content": content}, "sessionId": session, "timestamp": at, **flags})


def _write(tmp_path, lines, name="a.jsonl"):
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_only_typed_user_turns_are_kept(tmp_path):
    path = _write(
        tmp_path,
        [
            _line("user", "typed as a string"),
            _line("user", [{"type": "text", "text": "typed as a block"}]),
            _line("user", "summary of the past", isCompactSummary=True),
            _line("user", "meta", isMeta=True),
            _line("user", "agent turn", isSidechain=True),
            _line("user", [{"type": "tool_result", "content": "output"}]),
            _line("user", "<command-name>/x</command-name>"),
            _line("user", "[Request interrupted by user]"),
            _line("assistant", [{"type": "text", "text": "not a user"}]),
        ],
    )
    assert [t["text"] for t in ce.turns([path])] == ["typed as a string", "typed as a block"]


def test_a_turn_carries_what_claude_said_before_it(tmp_path):
    path = _write(
        tmp_path,
        [
            _line("assistant", [{"type": "text", "text": "first"}]),
            _line("assistant", [{"type": "tool_use", "name": "x"}, {"type": "text", "text": "second"}]),
            _line("assistant", [{"type": "tool_use", "name": "y"}]),
            _line("user", "no, not that", session="s9", at="2026-02-02T00:00:00Z"),
        ],
    )
    (turn,) = ce.turns([path])
    assert turn["before"] == "second"
    assert (turn["session"], turn["at"]) == ("s9", "2026-02-02T00:00:00Z")


def test_since_keeps_only_turns_from_that_time_on(tmp_path):
    path = _write(
        tmp_path,
        [_line("user", "old", at="2026-01-01T00:00:00Z"), _line("user", "new", at="2026-03-01T00:00:00Z")],
    )
    assert [t["text"] for t in ce.turns([path], since="2026-02-01")] == ["new"]


def test_before_keeps_only_the_end_of_a_long_answer(tmp_path):
    path = _write(tmp_path, [_line("assistant", [{"type": "text", "text": "x" * 5000 + "the end"}]), _line("user", "why?")])
    (turn,) = ce.turns([path])
    assert len(turn["before"]) == ce.BEFORE_CHARS and turn["before"].endswith("the end")


def _turn(text, session):
    return {"text": text, "session": session}


def test_verify_drops_quotes_that_are_not_in_a_turn_and_counts_sessions():
    turns = [_turn("please do not add a test for docs", "s1"), _turn("again: no test for a doc", "s2")]
    classes = [
        {"cause": "c", "quotes": ["no test for docs", "do not add a test", "no test for a doc", "invented"]},
        {"cause": "once", "quotes": ["do not add a test", "do not add a test"]},
    ]
    checked = ce.verify(classes, turns)
    first, second = checked
    assert first["quotes"] == ["do not add a test", "no test for a doc"]
    assert first["sessions"] == 2 and first["qualifies"]
    assert second["sessions"] == 1 and not second["qualifies"]


def test_a_quote_found_in_several_turns_is_too_generic_to_count():
    turns = [_turn("why do we need this file?", "s1"), _turn("why do we need two scripts?", "s2")]
    (checked,) = ce.verify([{"cause": "c", "quotes": ["why do we need"]}], turns)
    assert checked["quotes"] == [] and not checked["qualifies"]
