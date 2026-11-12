"""The command layout (CLAUDE.md → Code layout rules) stays patchable.

Tests patch a name on the module that defines it, which only reaches every caller when
callers look it up on that module. So src/door/ never imports a *name* from a command
module or from `door.core.workspace`, only the module; and `src/door/__init__.py`
re-exports nothing, so a stale `monkeypatch.setattr(door, ...)` fails loudly.
"""

import ast
import importlib

import click
import pytest

import door
from door.cli import cli
from paths import PACKAGE_DIR, REPO_ROOT

_SOURCES = sorted(PACKAGE_DIR.rglob("*.py"))


@pytest.mark.parametrize("path", _SOURCES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_module_imports_a_name_from_a_command_module_or_workspace(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            bad = node.module.startswith("door.commands.") or node.module == "door.core.workspace"
            assert not bad, f"{path.relative_to(REPO_ROOT)}:{node.lineno} imports names from {node.module}"


def test_package_init_reexports_nothing():
    public = [n for n in vars(door) if not n.startswith("__")]
    # submodules imported elsewhere show up as attributes; anything else is a re-export
    assert all(isinstance(getattr(door, n), type(door)) for n in public), public


def _commands(group, prefix=""):
    for name, cmd in group.commands.items():
        yield prefix + name, cmd
        if isinstance(cmd, click.Group):
            yield from _commands(cmd, prefix + name + " ")


@pytest.mark.parametrize("name,cmd", list(_commands(cli)), ids=lambda x: x if isinstance(x, str) else "")
def test_every_command_is_defined_in_a_command_module(name, cmd):
    module = importlib.import_module(cmd.callback.__module__)
    assert module.__name__.startswith("door.commands."), (name, module.__name__)
