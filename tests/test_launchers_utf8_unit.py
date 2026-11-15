"""#132: every way door's Python is started runs it in UTF-8 mode (PYTHONUTF8=1), so on Windows no text it
reads, writes or hands a program falls back to the code page (cp1252), library code included. The app's
two spawns are checked in app/src/main/door-server.test.ts, the generated `.mcp.json` and `claude mcp add`
in tests/core."""

import json
import re

from paths import REPO_ROOT


def test_the_shell_launcher_runs_python_in_utf8_mode():
    exec_line = next(line for line in (REPO_ROOT / "door").read_text(encoding="utf-8").splitlines() if " exec " in line)
    assert "PYTHONUTF8=1 " in exec_line


def test_the_windows_launcher_runs_python_in_utf8_mode():
    text = (REPO_ROOT / "door.cmd").read_text(encoding="utf-8")
    assert re.search(r'^set "PYTHONUTF8=1"$', text, re.MULTILINE)
    assert text.index('set "PYTHONUTF8=1"') < text.index("poetry ")


def test_the_committed_mcp_entry_runs_the_server_in_utf8_mode():
    entry = json.loads((REPO_ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["door"]
    assert entry["env"]["PYTHONUTF8"] == "1"
