"""The test world's scripted answers for `init`'s five prompt functions (app/test/world/prompts.py)."""

import json
import sys
import types

from paths import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "app" / "test" / "world"))
import prompts  # noqa: E402


def _module(tmp_path, script=None):
    if script is not None:
        (tmp_path / "prompts.json").write_text(json.dumps(script))
    module = types.SimpleNamespace()
    prompts.install(module, tmp_path)
    return module


def _calls(tmp_path):
    return [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]


def test_all_five_functions_are_replaced(tmp_path):
    module = _module(tmp_path)
    for name in ("text", "select", "checkbox", "confirm", "key"):
        assert callable(getattr(module, name))


def test_a_scripted_answer_is_returned(tmp_path):
    module = _module(tmp_path, {"name": {"answer": "Mette"}, "ok": {"answer": True}})
    assert module.text("name", "Your name", default="x") == "Mette"
    assert module.confirm("ok", "Sure?", default=False) is True


def test_a_sequence_is_walked_then_the_default(tmp_path):
    module = _module(tmp_path, {"review": {"sequence": ["edit", "save"]}})
    assert [module.select("review", "?", choices=[], default="d") for _ in range(3)] == ["edit", "save", "d"]


def test_an_unscripted_name_gets_the_default(tmp_path):
    module = _module(tmp_path, {})
    assert module.text("email", "Email", default="a@b.c") == "a@b.c"
    assert module.checkbox("pick", "Pick", choices=[], default=["x"]) == ["x"]
    assert module.key("k", "Key", keys={"q": "quit"}, default="q") == "q"


def test_a_missing_script_means_defaults(tmp_path):
    assert _module(tmp_path).text("n", "N", default="d") == "d"


def test_every_ask_is_logged(tmp_path):
    module = _module(tmp_path, {})
    module.text("a", "A")
    module.confirm("b", "B")
    assert [(c["kind"], c["name"]) for c in _calls(tmp_path)] == [("prompt", "a"), ("prompt", "b")]
