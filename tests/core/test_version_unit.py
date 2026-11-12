"""One version for door and its desktop app (#224): pyproject.toml, src/door/version.py (what the bundled
server reports, since a packaged app carries no pyproject.toml) and app/package.json. scripts/set_version.py
changes all three."""

import json
import tomllib

from paths import REPO_ROOT

from door import version


def test_the_three_places_agree():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]["version"]
    package = json.loads((REPO_ROOT / "app" / "package.json").read_text())["version"]
    lock = json.loads((REPO_ROOT / "app" / "package-lock.json").read_text())
    assert version.VERSION == pyproject == package == lock["version"] == lock["packages"][""]["version"]


def test_the_server_says_its_version_in_initialize():
    from door import mcp_server

    assert mcp_server.mcp._mcp_server.create_initialization_options().server_version == version.VERSION


def test_set_version_changes_all_three(tmp_path):
    import importlib.util
    import shutil

    for rel in ("pyproject.toml", "app/package.json", "app/package-lock.json", "src/door/version.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, tmp_path / rel)
    spec = importlib.util.spec_from_file_location("set_version", REPO_ROOT / "scripts" / "set_version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.set_version("9.8.7", root=tmp_path)
    assert tomllib.loads((tmp_path / "pyproject.toml").read_text())["project"]["version"] == "9.8.7"
    assert json.loads((tmp_path / "app" / "package.json").read_text())["version"] == "9.8.7"
    assert 'VERSION = "9.8.7"' in (tmp_path / "src" / "door" / "version.py").read_text()
    lock = json.loads((tmp_path / "app" / "package-lock.json").read_text())
    assert lock["version"] == "9.8.7" and lock["packages"][""]["version"] == "9.8.7"
