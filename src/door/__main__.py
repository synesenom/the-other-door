"""Allows `python -m door` to run the CLI — what ./door and door.cmd do."""

from door.cli import cli
from door.core import problem_log

if __name__ == "__main__":
    problem_log.setup()  # <data folder>/logs/door.log (#593)
    cli(prog_name="door")
