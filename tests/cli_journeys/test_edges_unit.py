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
from door.core import drive
print(json.dumps({
    "refused": refused,
    "now": datetime.now(timezone.utc).isoformat(),
    "drive": str(drive._BASE),
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
