"""The world's edges (app/test/world/edges.py) installed by import alone, as the CLI hook does."""

import json
import os
import subprocess
import time
import sys

from paths import REPO_ROOT, SRC_DIR

WORLD_DIR = REPO_ROOT / "app" / "test" / "world"


def test_importing_edges_installs_the_edges(tmp_path):
    (tmp_path / "world.json").write_text(json.dumps({"now": "2026-03-02T09:00:00+00:00", "boards": {}, "feeds": {}}))
    code = """
import json, socket, sys
from datetime import timezone
sys.path.insert(0, %r)
import edges
from datetime import datetime
try:
    socket.socket().connect(("example.com", 80))
    refused = False
except ConnectionRefusedError:
    refused = True
from door.core import workspace
print(json.dumps({
    "refused": refused,
    "now": datetime.now(timezone.utc).isoformat(),
    "drive": str(workspace.CONFIG_BASE),
    "mcp": "door.mcp_server" in sys.modules,
    "stacks": (edges.WORLD / "server-stacks.txt").exists(),
}))
""" % str(WORLD_DIR)
    env = {**os.environ, "DOOR_WORLD": str(tmp_path), "PYTHONPATH": str(SRC_DIR)}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["refused"]
    assert got["now"].startswith("2026-03-02T09:0")
    assert got["drive"] == str(tmp_path / "config")
    assert not got["mcp"]
    assert not got["stacks"]


def test_a_continuous_clock_goes_on_across_processes(tmp_path):
    """The CLI is a process per command: the world's time must not start again at `now` in each (the ledger orders events by it)."""
    (tmp_path / "world.json").write_text(json.dumps({"now": "2026-03-02T09:00:00+00:00", "boards": {}, "feeds": {}}))
    code = "import sys; sys.path.insert(0, %r); import edges; from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())" % str(WORLD_DIR)
    env = {**os.environ, "DOOR_WORLD": str(tmp_path), "PYTHONPATH": str(SRC_DIR), "DOOR_WORLD_CLOCK": "continuous"}

    def run():
        return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout.strip()

    first = run()
    time.sleep(1.2)
    second = run()
    assert second > first
    assert (tmp_path / "clock-start.txt").exists()


def test_a_door_process_the_server_starts_detached_gets_the_hook(tmp_path):
    """The CV style build is `python -m door ...` started detached by the server with its own PYTHONPATH: the world's hook rides along (#150)."""
    (tmp_path / "world.json").write_text(json.dumps({"now": "2026-03-02T09:00:00+00:00", "boards": {}, "feeds": {}}))
    code = """
import json, subprocess, sys
sys.path.insert(0, %r)
import edges
from pathlib import Path
from door.core import process
seen = []
subprocess.Popen = lambda argv, **kw: seen.append([argv, kw["env"]])
process.spawn_detached([sys.executable, "-m", "door", "cv", "style", "build", "x.pdf"], log=Path(%r), env={"PYTHONPATH": "/the/src", "DOOR_WORLD": %r})
process.spawn_detached([sys.executable, "-c", "pass"], log=Path(%r), env={"PYTHONPATH": "/the/src"})
print(json.dumps([e["PYTHONPATH"] for _, e in seen]))
""" % (str(WORLD_DIR), str(tmp_path / "a.log"), str(tmp_path), str(tmp_path / "b.log"))
    env = {**os.environ, "DOOR_WORLD": str(tmp_path), "PYTHONPATH": str(SRC_DIR)}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    door, other = json.loads(out.stdout.strip().splitlines()[-1])
    assert door.split(os.pathsep) == ["/the/src", str(WORLD_DIR / "hook")]
    assert other == "/the/src"
