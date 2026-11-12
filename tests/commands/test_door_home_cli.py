"""`DOOR_HOME` end to end (#216): the real CLI in a subprocess keeps its data in that folder and
leaves the checkout alone."""

import os
import subprocess
import sys

from paths import REPO_ROOT


def _tree(root):
    return sorted((str(p.relative_to(root)), p.stat().st_mtime_ns) for p in root.rglob("*")
                  if ".git" not in p.parts and "__pycache__" not in p.parts and ".venv" not in p.parts)


def _door(tmp_path, home, *args):
    env = {
        **os.environ, "DOOR_HOME": str(home), "PYTHONPATH": str(REPO_ROOT / "src"),
        "HOME": str(tmp_path / "userhome"), "XDG_CONFIG_HOME": str(tmp_path / "userhome" / ".config"),
        "APPDATA": str(tmp_path / "userhome" / "appdata"),
    }
    return subprocess.run([sys.executable, "-m", "door", *args], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=120)


def test_init_jobs_and_doctor_use_the_home_and_leave_the_checkout_alone(tmp_path):
    home = tmp_path / "data"
    home.mkdir()
    before = {n: _tree(REPO_ROOT / n) for n in ("profile", "jobs") if (REPO_ROOT / n).exists()}

    init = _door(tmp_path, home, "init", "--name", "Jane Doe", "--email", "jane@example.com",
                   "--location", "Copenhagen", "--role-targets", "data analyst")
    assert init.returncode == 0, init.stdout + init.stderr
    assert (home / "profile" / "config.json").exists()

    jobs = _door(tmp_path, home, "jobs")
    assert jobs.returncode == 0, jobs.stdout + jobs.stderr

    doctor = _door(tmp_path, home, "doctor")
    assert str(home.resolve()) in doctor.stdout + doctor.stderr

    after = {n: _tree(REPO_ROOT / n) for n in before}
    assert after == before
