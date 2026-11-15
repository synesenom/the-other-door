"""boot.py, the MCP entry the app journeys run: a `once` fault is used up when it is read (#33)."""

import json
import os
import subprocess
import sys

from paths import REPO_ROOT, SRC_DIR

BOOT = REPO_ROOT / "app" / "test" / "world" / "boot.py"


def test_a_once_fault_answers_once(tmp_path):
    (tmp_path / "world.json").write_text(json.dumps({"now": "2026-03-02T09:00:00+00:00", "boards": {}, "feeds": {}}))
    (tmp_path / "faults.json").write_text(json.dumps({"tools": {"show": {"error": "boom", "once": True}}}))
    code = f"""
import json, runpy, sys
sys.argv = ["boot.py", {str(tmp_path)!r}]
sys.path.insert(0, {str(BOOT.parent)!r})
ns = runpy.run_path({str(BOOT)!r}, run_name="boot_under_test")
print(json.dumps([ns["_fault_for"]("show"), ns["_fault_for"]("show")]))
"""
    env = {**os.environ, "PYTHONPATH": str(SRC_DIR)}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout.strip().splitlines()[-1]) == [{"error": "boom", "once": True}, None]
