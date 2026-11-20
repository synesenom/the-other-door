"""door.tailoring.facts (#433): the fact check is one cached Haiku call whose findings code holds to the text."""

import json

import pytest

from door.core import claude_cli, problem_log
from door.tailoring import facts

CV_MD = "### Dev | Acme - 2019\n- Team of 12\n"
BODY = '<ul><li>Cut churn by 40%</li><li>Team of&nbsp;12</li></ul>\n'
LETTER = "<p>I led 7 people.</p>"


@pytest.fixture
def dirs(tmp_path):
    out, prof = tmp_path / "out", tmp_path / "profile"
    out.mkdir(), prof.mkdir()
    (prof / "cv.md").write_text(CV_MD, encoding="utf-8")
    (out / "cv.html").write_text(BODY, encoding="utf-8")
    return out, prof


@pytest.fixture
def model(monkeypatch):
    """The one call, answered by `state["answer"]` (or raising it); `state["inputs"]` has what it was shown."""
    state = {"answer": {"findings": []}, "inputs": []}

    def fake(inputs):
        state["inputs"].append(inputs)
        if isinstance(state["answer"], Exception):
            raise state["answer"]
        return state["answer"]

    monkeypatch.setattr(facts, "_ask", fake)
    return state


def _finding(**kw):
    return {"kind": "number", "value": "40%", "context": "Cut churn by 40%", "file": "cv", **kw}


def test_a_finding_whose_context_is_in_the_text_is_kept(dirs, model):
    out, prof = dirs
    model["answer"] = {"findings": [_finding()]}
    found = facts.check(out, prof)
    assert found == [{"kind": "number", "value": "40%", "context": "Cut churn by 40%", "file": "cv"}]
    assert facts.load(out) == found


def test_the_model_is_shown_every_source_and_both_documents(dirs, model):
    out, prof = dirs
    (prof / "story_bank.md").write_text("A story of Rust.", encoding="utf-8")
    (out / "cover_letter.html").write_text(LETTER, encoding="utf-8")
    (out / "posting.json").write_text(json.dumps({"title": "Data lead", "description": "Own the platform."}), encoding="utf-8")
    facts.check(out, prof)
    shown = model["inputs"][0]
    for part in (CV_MD, "A story of Rust.", "Data lead", "Own the platform.", BODY, LETTER):
        assert part in shown


def test_a_context_not_in_the_text_is_dropped(dirs, model):
    out, prof = dirs
    model["answer"] = {"findings": [_finding(context="Cut churn by 99%"), _finding(value="12", context="Team of 12")]}
    assert [f["value"] for f in facts.check(out, prof)] == ["12"]  # the nbsp and the entity read as a space


def test_a_context_is_looked_for_in_the_file_it_names(dirs, model):
    out, prof = dirs
    (out / "cover_letter.html").write_text(LETTER, encoding="utf-8")
    model["answer"] = {"findings": [_finding(context="I led 7 people.", value="7", file="letter"),
                                    _finding(context="I led 7 people.", value="7", file="cv"),
                                    _finding(context="Cut churn by 40%", file="letter")]}
    assert [(f["value"], f["file"]) for f in facts.check(out, prof)] == [("7", "cover_letter")]


def test_a_finding_with_no_letter_to_hold_it_is_dropped(dirs, model):
    out, prof = dirs
    model["answer"] = {"findings": [_finding(file="letter")]}
    assert facts.check(out, prof) == []


def test_a_malformed_finding_is_dropped(dirs, model):
    out, prof = dirs
    model["answer"] = {"findings": ["x", {"kind": "number"}, _finding(kind="mood"), _finding(value=""), _finding()]}
    assert len(facts.check(out, prof)) == 1


def test_a_repeated_finding_is_listed_once(dirs, model):
    out, prof = dirs
    model["answer"] = {"findings": [_finding(), _finding()]}
    assert len(facts.check(out, prof)) == 1


def test_a_todo_is_flagged_by_code_without_the_model(dirs, model):
    out, prof = dirs
    (out / "cv.html").write_text("<p>Phone: TODO</p><p>MASTODON and TODOS</p>", encoding="utf-8")
    (out / "cover_letter.html").write_text("<!-- Tailoring: TODO tighten -->\n<p>Call me on TODO.</p>", encoding="utf-8")
    found = facts.check(out, prof)
    assert [(f["kind"], f["value"], f["file"]) for f in found] == [
        ("placeholder", "TODO", "cv"), ("placeholder", "TODO", "cover_letter")]
    assert "Phone" in found[0]["context"]


def test_clean_is_an_empty_list(dirs, model):
    out, prof = dirs
    assert facts.check(out, prof) == [] and facts.load(out) == []


def test_nothing_to_check_is_none_and_asks_nothing(tmp_path, model):
    out, prof = tmp_path / "o", tmp_path / "p"
    out.mkdir(), prof.mkdir()
    assert facts.check(out, prof) is None
    (prof / "cv.md").write_text(CV_MD, encoding="utf-8")
    assert facts.check(out, prof) is None and model["inputs"] == []


def test_a_failed_call_is_none_writes_nothing_and_is_logged(dirs, model, monkeypatch):
    out, prof = dirs
    logged = []
    monkeypatch.setattr(problem_log, "failure", lambda where, msg: logged.append(where))
    model["answer"] = claude_cli.ClaudeError("limit")
    assert facts.check(out, prof) is None
    assert not (out / "facts.json").exists() and logged == ["facts"]


def test_the_same_inputs_make_no_second_call(dirs, model):
    out, prof = dirs
    model["answer"] = {"findings": [_finding()]}
    first = facts.check(out, prof)
    assert facts.check(out, prof) == first and len(model["inputs"]) == 1


@pytest.mark.parametrize("change", ["cv.md", "story_bank.md", "cv.html", "cover_letter.html", "posting.json"])
def test_any_input_change_asks_again(dirs, model, change):
    out, prof = dirs
    facts.check(out, prof)
    where = prof if change in ("cv.md", "story_bank.md") else out
    (where / change).write_text(CV_MD + "x" if change == "cv.md" else '{"title": "x"}' if change == "posting.json" else "<p>x</p>",
                                encoding="utf-8")
    facts.check(out, prof)
    assert len(model["inputs"]) == 2


def test_a_facts_file_without_the_key_is_a_miss(dirs, model):
    out, prof = dirs
    (out / "facts.json").write_text(json.dumps({"checked_at": "x", "unsupported": []}), encoding="utf-8")
    facts.check(out, prof)
    assert len(model["inputs"]) == 1
    assert {"inputs_sha", "version", "checked_at", "unsupported"} <= set(json.loads((out / "facts.json").read_text()))


def test_write_false_writes_nothing(dirs, model):
    out, prof = dirs
    model["answer"] = {"findings": [_finding()]}
    assert len(facts.check(out, prof, write=False)) == 1
    assert not (out / "facts.json").exists()


def test_load_missing_or_corrupt(tmp_path):
    assert facts.load(tmp_path) is None
    (tmp_path / "facts.json").write_text("{nope")
    assert facts.load(tmp_path) is None


def _keep(**kw):
    return {"value": "40%", "kind": "number", "file": "cv", "reason": "from the ad", **kw}


def test_keep_writes_a_reason_and_a_cached_check_keeps_it_without_a_call(dirs, model):
    out, prof = dirs
    model["answer"] = {"findings": [_finding()]}
    facts.check(out, prof)
    found = facts.check(out, prof, keep=[_keep()])
    assert found[0]["reason"] == "from the ad" and len(model["inputs"]) == 1
    assert facts.load(out)[0]["reason"] == "from the ad"
    assert facts.check(out, prof)[0]["reason"] == "from the ad"  # kept on a rerun while it is flagged


def test_a_reason_goes_when_the_item_is_not_flagged_any_more(dirs, model):
    out, prof = dirs
    model["answer"] = {"findings": [_finding()]}
    facts.check(out, prof, keep=[_keep()])
    model["answer"] = {"findings": []}
    (out / "cv.html").write_text(BODY + "<p>more</p>", encoding="utf-8")
    assert facts.check(out, prof) == []


def test_keep_for_an_unflagged_item_and_a_placeholder_is_ignored(dirs, model):
    out, prof = dirs
    (out / "cv.html").write_text("<p>TODO</p>", encoding="utf-8")
    found = facts.check(out, prof, keep=[_keep(value="99%"), _keep(value="TODO", kind="placeholder")])
    assert all("reason" not in f for f in found)


def test_a_reason_is_cleaned(dirs, model):
    out, prof = dirs
    model["answer"] = {"findings": [_finding()]}
    reason = facts.check(out, prof, keep=[_keep(reason="a\n\tb\x07" + "x" * 300)])[0]["reason"]
    assert len(reason) == 200 and reason.startswith("a b") and "\n" not in reason and "\x07" not in reason


def test_write_false_merges_saved_reasons_without_writing(dirs, model):
    out, prof = dirs
    model["answer"] = {"findings": [_finding()]}
    facts.check(out, prof, keep=[_keep()])
    before = (out / "facts.json").read_text(encoding="utf-8")
    assert facts.check(out, prof, write=False)[0]["reason"] == "from the ad"
    assert (out / "facts.json").read_text(encoding="utf-8") == before
