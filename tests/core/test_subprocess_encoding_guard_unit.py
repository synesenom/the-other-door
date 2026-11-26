"""Guard: every program door talks to in text, and every text file it reads or writes, is UTF-8, never the
system's code page.

`text=True` alone encodes the input and decodes the output with the locale's encoding: cp1252 on a
Western Windows, which has no room for most of Unicode. A French CV whose PDF text held U+FFFE broke the
onboarding wizard there ("'charmap' codec can't encode character '\\ufffe'"); `claude` reads and writes
UTF-8 everywhere. So each text-mode call under `src/door/` names its `encoding`. The same holds for files:
door writes `cv.md` and the postings as UTF-8, and a bare `read_text()` reads them back in cp1252 there
(mojibake, or a `UnicodeDecodeError` on a "”" or an "Á").
"""

import ast
import subprocess

from door.core import claude_cli
from paths import REPO_ROOT


def _text_calls_without_encoding() -> list[str]:
    found = []
    for path in sorted((REPO_ROOT / "src" / "door").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            keywords = {k.arg: k.value for k in node.keywords}
            text = keywords.get("text", keywords.get("universal_newlines"))
            if isinstance(text, ast.Constant) and text.value is True and "encoding" not in keywords:
                found.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    return found


def test_every_text_mode_program_call_names_its_encoding():
    assert _text_calls_without_encoding() == []


def test_a_claude_call_sends_and_reads_utf8(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)
    claude_cli.run([], input="Mathématiques appli￾quées", feature="ask")
    assert seen["encoding"] == "utf-8"
    # whatever the input holds, it goes as UTF-8 (cp1252 could not)
    seen["input"].encode(seen["encoding"], errors=seen.get("errors", "strict"))


# receivers whose `.open` is no text file: archives, file descriptors, images, the browser
_NOT_TEXT_OPENERS = {"tarfile", "os", "Image", "zipfile", "zf", "webbrowser"}


def _mode(node: ast.Call, position: int) -> str:
    for k in node.keywords:
        if k.arg == "mode" and isinstance(k.value, ast.Constant):
            return str(k.value.value)
    if len(node.args) > position and isinstance(node.args[position], ast.Constant):
        return str(node.args[position].value)
    return "r"


def _text_files_without_encoding() -> list[str]:
    found = []
    for path in sorted((REPO_ROOT / "src" / "door").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or "encoding" in {k.arg for k in node.keywords}:
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == "open":
                text = "b" not in _mode(node, 1)
            elif isinstance(func, ast.Attribute) and func.attr in {"read_text", "write_text"}:
                text = True
            elif (isinstance(func, ast.Attribute) and func.attr == "open"
                  and not (isinstance(func.value, ast.Name) and func.value.id in _NOT_TEXT_OPENERS)):
                text = "b" not in _mode(node, 0)
            else:
                text = False
            if text:
                found.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    return found


def test_every_text_file_door_reads_or_writes_names_its_encoding():
    assert _text_files_without_encoding() == []
