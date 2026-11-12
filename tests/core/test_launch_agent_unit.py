"""`serve install-agent` (#302): a launchd agent per person that keeps their `door serve` running."""

import plistlib

import pytest

from door.core import launch_agent


def test_the_plist_runs_serve_for_one_home_and_keeps_it_alive(tmp_path):
    data = launch_agent.plist(home=tmp_path / "anna", port=8766, name="Anna", python="/py/bin/python3", src="/repo/src", path="/usr/bin:/bin")
    assert data["Label"] == "dev.door.serve.anna"
    assert data["ProgramArguments"] == ["/py/bin/python3", "-m", "door", "serve", "start", "--port", "8766", "--name", "Anna"]
    assert data["EnvironmentVariables"]["DOOR_HOME"] == str(tmp_path / "anna")
    assert data["EnvironmentVariables"]["PYTHONPATH"] == "/repo/src"
    assert data["KeepAlive"] is True and data["RunAtLoad"] is True
    assert data["StandardErrorPath"] == str(tmp_path / "anna" / "logs" / "serve.log")


def test_install_writes_the_agent_and_loads_it(tmp_path):
    ran = []
    path = launch_agent.install(home=tmp_path / "anna", port=8766, name="Anna Larsen", agents_dir=tmp_path / "agents",
                                platform="darwin", run=lambda argv, **kw: ran.append(argv), uid=501)
    assert path.name == "dev.door.serve.anna-larsen.plist"
    assert plistlib.loads(path.read_bytes())["Label"] == "dev.door.serve.anna-larsen"
    assert ran[-1] == ["launchctl", "bootstrap", "gui/501", str(path)]


def test_uninstall_unloads_and_removes(tmp_path):
    ran = []
    path = launch_agent.install(home=tmp_path / "a", port=1, name="Anna", agents_dir=tmp_path, platform="darwin", run=lambda argv, **kw: None, uid=501)
    assert launch_agent.uninstall(name="Anna", agents_dir=tmp_path, platform="darwin", run=lambda argv, **kw: ran.append(argv), uid=501) == path
    assert not path.exists()
    assert ran == [["launchctl", "bootout", "gui/501", str(path)]]
    assert launch_agent.uninstall(name="Anna", agents_dir=tmp_path, platform="darwin", run=lambda argv, **kw: None, uid=501) is None


def test_only_on_macos(tmp_path):
    with pytest.raises(ValueError, match="macOS"):
        launch_agent.install(home=tmp_path, port=1, name="A", agents_dir=tmp_path, platform="linux", run=None, uid=0)
