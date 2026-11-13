"""Guard (#18): every program door starts gets its own stdin (`input=` or `stdin=`), never the server's.

The MCP server reads its JSON-RPC stream from stdin on a thread. On Windows a child that inherits that pipe
while the read is pending hangs as it starts (the install test's stand-in claude.cmd timed out after 15 s);
anywhere, one that reads it would take the server's messages. So no `subprocess` call under `src/door/`
leaves stdin to be inherited.
"""

import ast
import subprocess

import pytest

from door.core import claude_cli
from paths import REPO_ROOT

_STARTS = {"run", "Popen", "check_output", "check_call", "call"}


def _inheriting_calls() -> list[str]:
    found = []
    for path in sorted((REPO_ROOT / "src" / "door").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _STARTS
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"
                    and not {k.arg for k in node.keywords} & {"stdin", "input"}):
                found.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    return found


def test_no_program_door_starts_inherits_the_servers_stdin():
    assert _inheriting_calls() == []


def test_a_claude_call_without_input_gets_an_empty_stdin(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout='{"type":"result","is_error":false,"result":"ok"}', stderr="")

    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(claude_cli.usage, "record", lambda *a, **k: None, raising=False)
    try:
        claude_cli.run(["-p", "hi"], feature="ask")
    except Exception as exc:  # what it does with the answer is not this test's business
        if not seen:
            pytest.fail(f"claude_cli.run never started claude: {exc}")
    assert seen.get("stdin") is subprocess.DEVNULL or seen.get("input") is not None, seen
