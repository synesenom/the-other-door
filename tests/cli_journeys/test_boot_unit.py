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


def test_stacks_are_written_under_the_gil_and_a_crash_is_reported(tmp_path):
    """The server's stacks come from sys._current_frames on a Python thread, not faulthandler's watchdog, which
    walks the threads without the GIL and can crash the server when one starts or ends (#98); a native crash is
    reported on stderr."""
    (tmp_path / "world.json").write_text(json.dumps({"now": "2026-03-02T09:00:00+00:00", "boards": {}, "feeds": {}}))
    code = f"""
import faulthandler, json, runpy, sys, threading
sys.argv = ["boot.py", {str(tmp_path)!r}]
sys.path.insert(0, {str(BOOT.parent)!r})
ns = runpy.run_path({str(BOOT)!r}, run_name="boot_under_test")
gate = threading.Event()
def parked_here():
    gate.wait()
t = threading.Thread(target=parked_here, daemon=True)
t.start()
ns["_write_stacks"]()
gate.set()
print(json.dumps(faulthandler.is_enabled()))
"""
    env = {**os.environ, "PYTHONPATH": str(SRC_DIR)}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout.strip().splitlines()[-1]) is True
    stacks = (tmp_path / "server-stacks.txt").read_text(encoding="utf-8")
    assert "Thread 0x" in stacks
    assert "parked_here" in stacks
