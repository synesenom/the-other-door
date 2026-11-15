"""Allows `python -m door` to run the CLI — what ./door and door.cmd do."""

import sys

from door.cli import cli
from door.core import problem_log


def tolerant_streams() -> None:
    """A mark the console or pipe cannot spell (✗ on a Windows cp1252 pipe) prints as `?`, not a crash."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


if __name__ == "__main__":
    tolerant_streams()
    problem_log.setup()  # <data folder>/logs/door.log (#593)
    cli(prog_name="door")
