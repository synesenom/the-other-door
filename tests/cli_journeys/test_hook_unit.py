"""The CLI journeys' sitecustomize hook touches only `python -m door` inside a world (app/test/world/hook)."""

import importlib.util
import subprocess
import sys

from paths import REPO_ROOT

HOOK = REPO_ROOT / "app" / "test" / "world" / "hook"


def _load():
    # Importing it with no DOOR_WORLD does nothing, so it is safe to load by path here.
    spec = importlib.util.spec_from_file_location("world_hook_sitecustomize", HOOK / "sitecustomize.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wanted_only_for_python_dash_m_door_in_a_world():
    wanted = _load()._wanted
    assert wanted(["python", "-m", "door", "find"], {"DOOR_WORLD": "/w"})
    assert not wanted(["python", "-m", "door"], {})
    assert not wanted(["python", "-c", "print(1)"], {"DOOR_WORLD": "/w"})
    assert not wanted(["/venv/bin/poetry", "run", "python", "-m", "door"], {"DOOR_WORLD": "/w"})
    assert not wanted(["python", "-m", "pytest"], {"DOOR_WORLD": "/w"})


def test_another_interpreter_in_a_world_is_untouched(tmp_path):
    import os

    env = {**os.environ, "PYTHONPATH": str(HOOK), "DOOR_WORLD": str(tmp_path)}
    out = subprocess.run([sys.executable, "-c", "import sys; print('edges' in sys.modules)"],
                         env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
