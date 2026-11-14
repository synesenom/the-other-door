"""Every Claude call reports its usage (#575): each `claude_cli.run`/`ask` call under `src/door/`
names a known `feature=` (what each call site records: `test_claude_call_sites_unit.py`)."""

import ast

from door.core import usage
from paths import REPO_ROOT

SRC = REPO_ROOT / "src" / "door"


def _calls(tree, names):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in names
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "claude_cli"):
            yield node


def test_every_claude_cli_call_names_a_known_feature():
    seen = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _calls(tree, {"run", "ask"}):
            kw = {k.arg: k.value for k in call.keywords}
            where = f"{path.relative_to(SRC)}:{call.lineno}"
            assert "feature" in kw, f"{where} calls claude_cli.{call.func.attr} without feature="
            assert isinstance(kw["feature"], ast.Constant), f"{where}: feature= must be a literal"
            assert kw["feature"].value in usage.FEATURES, f"{where}: unknown feature {kw['feature'].value!r}"
            seen.append(kw["feature"].value)
    assert len(seen) >= 12
