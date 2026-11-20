"""`ask_cached.cached_answer`: a checked model answer, cached by a key, asked again when it does not hold."""

import json

import pytest

from door.core import ask_cached, claude_cli, problem_log


class Bad(ValueError):
    pass


def _check(answer):
    if answer.get("n") != 1:
        raise Bad("n is not 1")
    return {"checked": answer["n"]}


def _unreached(exc):
    return Bad(f"unreached: {exc}")


def _run(tmp_path, asks, keep=20, **kw):
    calls = []

    def ask():
        calls.append(1)
        item = asks[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    out = ask_cached.cached_answer(key="k", version=2, ask=ask, check=_check, error=Bad, unreached=_unreached,
                                   label="thing", store=ask_cached.DirStore(tmp_path, keep), **kw)
    return out, calls


def test_ask_then_hit(tmp_path):
    out, calls = _run(tmp_path, [{"n": 1}])
    assert out == {"checked": 1} and len(calls) == 1
    assert json.loads((tmp_path / "k.json").read_text()) == {"version": 2, "answer": {"n": 1}}
    out, calls = _run(tmp_path, [])
    assert out == {"checked": 1} and calls == []


def test_tag_is_part_of_the_hit(tmp_path):
    _run(tmp_path, [{"n": 1}], tag="a")
    assert json.loads((tmp_path / "k.json").read_text())["rows"] == "a"
    _, calls = _run(tmp_path, [{"n": 1}], tag="b")
    assert len(calls) == 1


def test_other_version_is_a_miss(tmp_path):
    (tmp_path / "k.json").write_text(json.dumps({"version": 1, "answer": {"n": 1}}))
    _, calls = _run(tmp_path, [{"n": 1}])
    assert len(calls) == 1


def test_cached_answer_that_no_longer_holds_is_asked_again(tmp_path):
    (tmp_path / "k.json").write_text(json.dumps({"version": 2, "answer": {"n": 5}}))
    out, calls = _run(tmp_path, [{"n": 1}])
    assert out == {"checked": 1} and len(calls) == 1


def test_a_bad_answer_is_asked_once_more(tmp_path):
    out, calls = _run(tmp_path, [{"n": 0}, {"n": 1}])
    assert out == {"checked": 1} and len(calls) == 2


def test_two_bad_answers_raise_log_and_cache_nothing(tmp_path, monkeypatch):
    logged = []
    monkeypatch.setattr(problem_log, "failure", lambda where, msg: logged.append((where, str(msg))))
    with pytest.raises(Bad):
        _run(tmp_path, [{"n": 0}, {"n": 0}])
    assert logged == [("thing", "n is not 1")]
    assert not list(tmp_path.glob("*.json"))


def test_a_failed_call_is_the_callers_error_and_not_retried(tmp_path, monkeypatch):
    logged = []
    monkeypatch.setattr(problem_log, "failure", lambda where, msg: logged.append(where))
    with pytest.raises(Bad, match="unreached: boom"):
        _run(tmp_path, [claude_cli.ClaudeError("boom")])
    assert logged == ["thing"]


def test_only_the_newest_are_kept(tmp_path):
    import os
    for i in range(5):
        f = tmp_path / f"old{i}.json"
        f.write_text("{}")
        os.utime(f, (1000 + i, 1000 + i))
    _run(tmp_path, [{"n": 1}], keep=3)
    assert len(list(tmp_path.glob("*.json"))) == 3 and (tmp_path / "k.json").exists()
