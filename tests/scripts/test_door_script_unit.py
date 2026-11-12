"""Unit tests for ./door (and door.cmd): the command line's one entry point.

`./door <command>` runs `python -m door <command>` in the project's Poetry
environment with src/ on PYTHONPATH (the package lives in src/door/ and is never
installed). The script runs on a PATH holding a fake `poetry` that logs its
arguments, PYTHONPATH and working directory, plus the few real utilities it uses.
"""

import os
import shutil
import subprocess
import sys

import pytest
from paths import REPO_ROOT, SRC_DIR

DOOR = REPO_ROOT / "door"
DOOR_CMD = REPO_ROOT / "door.cmd"

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="./door is the macOS/Linux script")


def _run(tmp_path, *args, cwd=None, exit_code=0, pythonpath=None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("bash", "dirname", "env"):
        (bin_dir / name).symlink_to(shutil.which(name))
    log = tmp_path / "calls.log"
    fake = bin_dir / "poetry"
    fake.write_text(
        "#!/bin/bash\n"
        f'echo "args $*" >> "{log}"\n'
        f'echo "argc $#" >> "{log}"\n'
        f'echo "pythonpath $PYTHONPATH" >> "{log}"\n'
        f'echo "cwd $PWD" >> "{log}"\n'
        f"exit {exit_code}\n"
    )
    fake.chmod(0o755)
    env = {"PATH": str(bin_dir), "HOME": str(tmp_path)}
    if pythonpath:
        env["PYTHONPATH"] = pythonpath
    proc = subprocess.run(
        [str(DOOR), *args], cwd=cwd or tmp_path, env=env, capture_output=True, text=True, timeout=30
    )
    lines = dict(line.split(" ", 1) for line in log.read_text().splitlines()) if log.exists() else {}
    return proc, lines


@posix_only
def test_door_is_an_executable_file():
    assert DOOR.is_file()
    assert os.access(DOOR, os.X_OK)


@posix_only
def test_door_runs_the_cli_in_the_projects_poetry_environment(tmp_path):
    proc, calls = _run(tmp_path, "jobs", "list", "--new", cwd=REPO_ROOT)
    assert proc.returncode == 0, proc.stderr
    assert calls["args"] == f"-C {REPO_ROOT} run python -m door jobs list --new"
    assert calls["pythonpath"] == str(SRC_DIR)


@posix_only
def test_door_keeps_the_working_directory(tmp_path):
    # `./door export` writes into the current folder, so the script must not cd.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    proc, calls = _run(tmp_path, "export", cwd=elsewhere)
    assert proc.returncode == 0, proc.stderr
    assert calls["cwd"] == str(elsewhere)
    assert calls["pythonpath"] == str(SRC_DIR)


@posix_only
def test_door_keeps_an_existing_pythonpath(tmp_path):
    _, calls = _run(tmp_path, "status", pythonpath="/opt/extra")
    assert calls["pythonpath"] == f"{SRC_DIR}:/opt/extra"


@posix_only
def test_door_passes_the_exit_code_on(tmp_path):
    proc, _ = _run(tmp_path, "scrape", exit_code=2)
    assert proc.returncode == 2


@posix_only
def test_door_passes_arguments_with_spaces_intact(tmp_path):
    _, calls = _run(tmp_path, "discard", "3", "--reason", "too far away")
    assert calls["args"].endswith("discard 3 --reason too far away")
    assert calls["argc"] == "10"  # -C <repo> run python -m door discard 3 --reason "too far away"


@posix_only
def test_door_really_starts_the_cli():
    proc = subprocess.run([str(DOOR), "--help"], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "Automated job hunting pipeline" in proc.stdout
    assert proc.stdout.startswith("Usage: door ")  # not "python -m door"


def test_door_cmd_is_the_windows_twin():
    text = DOOR_CMD.read_text()
    assert 'poetry -C "%REPO%" run python -m door %*' in text
    assert 'PYTHONPATH=%REPO%\\src' in text
    assert "exit /b" in text


def test_line_endings_are_pinned():
    attributes = (REPO_ROOT / ".gitattributes").read_text()
    assert "/door text eol=lf" in attributes
    assert "/door.cmd text eol=crlf" in attributes
