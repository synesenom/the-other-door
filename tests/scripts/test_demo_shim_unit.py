"""scripts/demo/shim.py: the demo recordings prepare a job on a computer with no claude and no Chromium."""

import os
import subprocess
import sys

from paths import REPO_ROOT

_CHECK = """
import sys
from pathlib import Path
import shim
shim.install(Path(sys.argv[1]))
from door.commands import _common
assert _common._claude_available(), "claude"
assert _common._chromium_available(), "chromium"
"""


def test_prepare_needs_neither_claude_nor_chromium(tmp_path):
    # the stand-in tailor writes the PDFs itself, so nothing prints them: prepare must not refuse for want
    # of the pinned Chromium (the phone GIF recorder stopped at "nothing prepared", #294)
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "DOOR_BIN": str(tmp_path / "no-bin"),
           "PYTHONPATH": os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT / "scripts" / "demo")])}
    done = subprocess.run([sys.executable, "-c", _CHECK, str(tmp_path / "sandbox")], env=env,
                          capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
