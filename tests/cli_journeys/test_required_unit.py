"""Where the CLI journeys are required (CI, the release gate) a missing prerequisite fails; elsewhere it skips (#33)."""

import pytest

import cli_world


@pytest.mark.parametrize("env", [{"CI": "true"}, {"DOOR_CLI_JOURNEYS_REQUIRED": "1"}])
def test_a_missing_prerequisite_fails_where_required(monkeypatch, env):
    monkeypatch.delenv("DOOR_PYTHON", raising=False)
    monkeypatch.delenv("CI", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(pytest.fail.Exception):
        cli_world.build_world()


def test_a_missing_prerequisite_skips_elsewhere(monkeypatch):
    monkeypatch.delenv("DOOR_PYTHON", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("DOOR_CLI_JOURNEYS_REQUIRED", raising=False)
    with pytest.raises(pytest.skip.Exception):
        cli_world.build_world()
