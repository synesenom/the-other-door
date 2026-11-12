"""Guard: nothing under src/door/ calls print() or imports tqdm (issue #202).

The MCP server speaks JSON-RPC on stdout, so a stray print() corrupts the
stream. Cores and scrapers report progress with `report()`, and Click
commands render with `click.echo`.
"""

import ast

from paths import PACKAGE_DIR, REPO_ROOT

_DOOR = PACKAGE_DIR


def _sources():
    return sorted(_DOOR.rglob("*.py"))


def test_door_never_calls_print():
    offenders = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert offenders == [], f"print() calls found (use progress.report / click.echo): {offenders}"


def test_door_does_not_import_tqdm():
    offenders = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "tqdm" for a in node.names):
                offenders.append(str(path.relative_to(REPO_ROOT)))
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "tqdm":
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
