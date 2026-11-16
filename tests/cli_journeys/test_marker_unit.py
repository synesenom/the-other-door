"""Only the tests under tests/cli_journeys/ carry the `cli_journeys` marker, which the default run deselects (#180)."""

import subprocess
import sys

from paths import REPO_ROOT


def test_a_test_outside_the_folder_is_not_marked_cli_journeys():
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-n0", "-m", "cli_journeys",
         "tests/commands/test_mcp_server.py", "tests/cli_journeys"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    ).stdout
    nodes = [line for line in out.splitlines() if "::" in line]
    assert nodes, out
    assert all(n.startswith("tests/cli_journeys/") for n in nodes), nodes
    assert not any(n.endswith("_unit.py") or "_unit.py::" in n for n in nodes)
