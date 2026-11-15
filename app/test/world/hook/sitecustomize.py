"""Test-only: puts the test world's edges and scripted prompts into the real `./door` (CLI journeys).

Python imports this at start when the hook folder is on PYTHONPATH. It does nothing unless DOOR_WORLD is set
and the interpreter was started as `python -m door`, so Poetry's own interpreter, `python -c` and every
other program stay untouched. A broken world fails loudly. No production code knows it.
"""

import os
import sys
from pathlib import Path


def _wanted(orig_argv, environ) -> bool:
    return bool(environ.get("DOOR_WORLD")) and list(orig_argv[1:3]) == ["-m", "door"]


if _wanted(getattr(sys, "orig_argv", []), os.environ):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import edges
    import prompts
    from door.commands import _prompts

    prompts.install(_prompts, edges.WORLD)
