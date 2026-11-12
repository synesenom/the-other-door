"""One `door serve` per person (#302): the machine's registry of served data folders and its refusals."""

import pytest

from door.core import instances


def test_register_lists_and_unregister_forgets(tmp_path):
    a = tmp_path / "anna"
    instances.register(a, port=8765, name="Anna", claude_config_dir=None)
    assert instances.read() == {str(a.resolve()): {"port": 8765, "name": "Anna", "claude_config_dir": None}}
    instances.register(a, port=8770, name="Anna", claude_config_dir=None)  # the same home again: updated
    assert instances.read()[str(a.resolve())]["port"] == 8770
    instances.unregister(a)
    assert instances.read() == {}


def test_two_people_need_two_ports(tmp_path):
    instances.register(tmp_path / "anna", port=8765, name="Anna", claude_config_dir="/c/anna")
    with pytest.raises(ValueError, match="port 8765"):
        instances.register(tmp_path / "ben", port=8765, name="Ben", claude_config_dir="/c/ben")


def test_two_people_never_share_a_claude_plan(tmp_path):
    instances.register(tmp_path / "anna", port=8765, name="Anna", claude_config_dir="/c/shared")
    with pytest.raises(ValueError, match="claude_config_dir"):
        instances.register(tmp_path / "ben", port=8766, name="Ben", claude_config_dir="/c/shared")


def test_a_second_person_needs_their_own_claude_config_dir(tmp_path):
    instances.register(tmp_path / "anna", port=8765, name="Anna", claude_config_dir=None)
    with pytest.raises(ValueError, match="claude_config_dir"):
        instances.register(tmp_path / "ben", port=8766, name="Ben", claude_config_dir=None)
    instances.register(tmp_path / "ben", port=8766, name="Ben", claude_config_dir="/c/ben")
    assert len(instances.read()) == 2
