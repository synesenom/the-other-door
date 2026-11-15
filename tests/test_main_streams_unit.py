"""`python -m door` writes to a console or pipe whose encoding cannot spell every mark (#33: Windows,
cp1252 on a pipe): a mark it cannot spell becomes `?`, never a crash."""

import io
import os
import subprocess
import sys

from paths import REPO_ROOT


def test_a_mark_the_stream_cannot_spell_is_replaced_not_raised(monkeypatch):
    from door import __main__ as main

    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))
    main.tolerant_streams()
    print("  ✗ MCP server")
    out.flush()
    assert out.buffer.getvalue() == b"  ? MCP server\n"


def test_a_process_on_a_cp1252_pipe_prints_a_question_mark():
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONPATH": str(REPO_ROOT / "src")}
    proc = subprocess.run([sys.executable, "-c", "from door import __main__ as m; m.tolerant_streams(); print('✗')"],
                          env=env, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == b"?"
