"""Fixtures shared by the command tests."""

import types
from collections.abc import Iterator

import pytest

from door.commands import _prompts
from door.core import workspace
from profile_utils import write_config


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Redirect The other door's PROFILE_DIR/JOBS_DIR into tmp and seed a config.json."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    write_config(profile_dir, {
        "role_targets": ["data scientist"],
        "location": "Copenhagen",
    })
    jobs_dir = tmp_path / "jobs"
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)
    return types.SimpleNamespace(profile_dir=profile_dir, jobs_dir=jobs_dir)


@pytest.fixture
def prompts(monkeypatch):
    """Replace the inquirer prompts (`src/door/commands/_prompts.py`) with scripted answers.

    `answers` maps a prompt's name to its answer, or to an iterator of answers
    for a prompt asked again and again (one per time, then the default); an
    unscripted prompt takes its default (pressing Enter). `asked` records each prompt's arguments by
    name, for asserting on the choices offered; `order` lists the names in
    the order they were asked.
    """
    scripted = types.SimpleNamespace(answers={}, asked={}, order=[])

    def fake(kind):
        def ask(name, message, **kwargs):
            scripted.asked[name] = {"kind": kind, "message": message, **kwargs}
            scripted.order.append(name)
            answer = scripted.answers.get(name, kwargs.get("default"))
            if isinstance(answer, Iterator):
                return next(answer, kwargs.get("default"))
            return answer
        return ask

    for kind in ("text", "select", "checkbox", "confirm", "key"):
        monkeypatch.setattr(_prompts, kind, fake(kind))
    return scripted
