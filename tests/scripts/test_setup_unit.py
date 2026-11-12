"""Unit tests for scripts/setup.sh: the bootstrap before `door doctor --fix`.

It finds (or installs) Python 3.12 and Poetry, installs the Python packages, then
hands over to `door doctor --fix --yes`. The script runs on a PATH holding only fakes
(`poetry`, `python3`, `python3.12`, `curl`, `brew`, `uv`) that log their calls, plus the few
real utilities it uses — so whatever Python the test machine has never leaks in.
"""

import os
import shutil
import subprocess
import sys

import pytest
from paths import REPO_ROOT

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="setup.sh is the macOS/Linux script")

UTILITIES = ("bash", "sh", "sed", "cat", "mktemp", "tail", "rm", "sleep", "dirname", "uname", "env")


def _fake(bin_dir, name, log, body=""):
    path = bin_dir / name
    path.write_text(f'#!/bin/bash\necho "{name} $*" >> "{log}"\n{body}\n')
    path.chmod(0o755)


def _python(version):
    return f'if [ "$1" = "-c" ]; then echo "{version}"; fi\nif [ "$1" = "--version" ]; then echo "Python {version}"; fi'


def _run(tmp_path, *, poetry="2.4.3", python3=None, python312=False, poetry_installed=True, brew=False, uv=False,
         curl=True, args=("--yes",), stdin=""):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    log = tmp_path / "calls.log"
    for name in UTILITIES:
        real = shutil.which(name)
        if real:
            (bin_dir / name).symlink_to(real)
    if poetry_installed:
        _fake(bin_dir, "poetry", log, f'if [ "$1" = "--version" ]; then echo "Poetry (version {poetry})"; fi')
    if python3:
        _fake(bin_dir, "python3", log, _python(python3))
    if python312:
        _fake(bin_dir, "python3.12", log, _python("3.12.6"))
    # the official installer pipes into python; the fake "installs" poetry by dropping one in HOME
    if curl:
        _fake(bin_dir, "curl", log, "echo 'true'")
    # a Python 3.12 that Homebrew or uv installs, off PATH
    installed = tmp_path / "installed" / "bin"
    installed.mkdir(parents=True)
    _fake(installed, "python3.12", log, _python("3.12.6"))
    if brew:
        _fake(bin_dir, "brew", log, f'if [ "$1" = "--prefix" ]; then echo "{installed.parent}"; fi')
    if uv:
        _fake(bin_dir, "uv", log, f'if [ "$1 $2" = "python find" ]; then echo "{installed / "python3.12"}"; fi')
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    env = {"PATH": str(bin_dir), "HOME": str(home), "LANG": "C.UTF-8"}
    proc = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "setup.sh"), *args],
        env=env, capture_output=True, text=True, timeout=30, input=stdin,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls


def test_poetry_1_stops_before_install_and_says_how_to_upgrade(tmp_path):
    proc, calls = _run(tmp_path, poetry="1.8.3", python312=True)
    assert proc.returncode != 0
    assert "poetry install" not in calls
    assert "1.8.3" in proc.stderr
    assert "poetry self update" in proc.stderr


def test_with_python_312_and_poetry_it_installs_the_packages_and_hands_over(tmp_path):
    proc, calls = _run(tmp_path, python312=True)
    assert proc.returncode == 0, proc.stderr
    assert "poetry install" in calls
    assert f"poetry -C {REPO_ROOT} run python -m door doctor --fix --yes" in calls
    assert not any(c.startswith("poetry python install") for c in calls)
    assert "✓ Python 3.12" in proc.stdout and "✓ Python packages" in proc.stdout


def test_a_python3_that_is_312_counts(tmp_path):
    proc, calls = _run(tmp_path, python3="3.12.6")
    assert proc.returncode == 0, proc.stderr
    assert not any(c.startswith("poetry python install") for c in calls)


def test_without_python_312_poetry_installs_it(tmp_path):
    proc, calls = _run(tmp_path, python3="3.9.6")
    assert proc.returncode == 0, proc.stderr
    assert "poetry python install 3.12" in calls
    assert calls.index("poetry python install 3.12") < calls.index("poetry install")
    assert "poetry env use 3.12" in calls


def test_installing_python_needs_poetry_2_1(tmp_path):
    proc, calls = _run(tmp_path, poetry="2.0.1", python3="3.9.6")
    assert proc.returncode != 0
    assert "poetry python install 3.12" not in calls and "poetry install" not in calls
    assert "poetry self update" in proc.stderr


def test_missing_poetry_is_installed_with_the_official_installer(tmp_path):
    proc, calls = _run(tmp_path, python312=True, poetry_installed=False)
    assert any(c.startswith("curl") and "install.python-poetry.org" in c for c in calls)


def test_no_python_and_no_poetry_uses_homebrew_when_there(tmp_path):
    proc, calls = _run(tmp_path, python3="3.9.6", poetry_installed=False, brew=True)
    assert "brew install python@3.12" in calls
    assert any(c.startswith("curl") and "install.python-poetry.org" in c for c in calls)
    assert "python3 -" not in calls, "the system 3.9 never runs Poetry's installer"
    assert "python3.12 -" in calls


def test_no_python_no_poetry_and_no_homebrew_gets_python_from_uv(tmp_path):
    proc, calls = _run(tmp_path, python3="3.9.6", poetry_installed=False, uv=True)
    assert "uv python install 3.12" in calls
    assert not any(c.startswith("brew") for c in calls)
    assert any(c.startswith("curl") and "install.python-poetry.org" in c for c in calls)


def test_uv_is_fetched_when_missing(tmp_path):
    proc, calls = _run(tmp_path, poetry_installed=False)
    assert any(c.startswith("curl") and "astral.sh/uv" in c for c in calls)


def test_python_that_cannot_be_installed_says_where_to_get_it(tmp_path):
    proc, calls = _run(tmp_path, poetry_installed=False)   # no uv appears after its installer
    assert proc.returncode != 0
    assert "Python 3.12" in proc.stderr and "python.org" in proc.stderr
    assert "poetry install" not in calls


def test_without_curl_it_says_so_before_installing_anything(tmp_path):
    proc, calls = _run(tmp_path, poetry_installed=False, curl=False)
    assert proc.returncode != 0
    assert "curl" in proc.stderr
    assert calls == []


def test_asks_once_before_installing_anything(tmp_path):
    proc, calls = _run(tmp_path, python312=True, args=(), stdin="n\n")
    assert proc.returncode != 0
    assert "Continue?" in proc.stdout
    assert "poetry install" not in calls

    proc, calls = _run(tmp_path / "yes", python312=True, args=(), stdin="\n")  # Enter = yes
    assert proc.returncode == 0, proc.stderr
    assert f"poetry -C {REPO_ROOT} run python -m door doctor --fix --yes" in calls


def test_passes_its_other_flags_on(tmp_path):
    proc, calls = _run(tmp_path, python312=True, args=("--yes", "--no-tex"))
    assert f"poetry -C {REPO_ROOT} run python -m door doctor --fix --yes --no-tex" in calls
