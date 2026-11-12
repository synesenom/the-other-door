"""Names stored on users' machines and Drive, after the rebrand to "The other door" (#452): the Drive folder
the user sees, the archive in it, the settings folder holding the Drive token, the phone server's launchd label."""

from door.core import drive, launch_agent


def test_drive_folder_and_archive():
    assert drive.FOLDER_NAME == "The other door"
    assert drive.FILE_NAME == "door-data.tar.gz"


def test_the_settings_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(drive, "_BASE", None)
    monkeypatch.setattr(drive.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert drive.state_path() == tmp_path / "door" / "drive.json"


def test_the_phone_server_agent_label():
    assert launch_agent.label("Anna") == "dev.door.serve.anna"
