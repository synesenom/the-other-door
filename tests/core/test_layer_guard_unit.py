"""Guard: the lower packages never import the command layer (issue #357).

`door.commands` composes the packages below it; `render/` and `style/` have no business reaching up
into it, and `render/` is also under `style/`. `pipeline/` is left out: it is the layer that composes
the commands' cores (`find`'s five steps). `core/sync.py` is the one named exception: its Drive hooks
call the archive core lazily, which moving would be a change of its own.
"""

import ast

from paths import PACKAGE_DIR, REPO_ROOT

LOWER = ("render", "style", "core", "tailoring", "matching", "i18n", "scrapers")
EXCEPTIONS = {"core/sync.py"}


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            yield node.lineno, node.module or ""
            for alias in node.names:
                yield node.lineno, f"{node.module}.{alias.name}"


def _offenders(packages, forbidden):
    found = []
    for package in packages:
        for path in sorted((PACKAGE_DIR / package).rglob("*.py")):
            if str(path.relative_to(PACKAGE_DIR)) in EXCEPTIONS:
                continue
            for line, name in _imports(path):
                if name == forbidden or name.startswith(forbidden + "."):
                    found.append(f"{path.relative_to(REPO_ROOT)}:{line} imports {name}")
    return sorted(set(found))


def test_the_lower_packages_never_import_the_commands():
    assert _offenders(LOWER, "door.commands") == []


def test_render_never_imports_style():
    assert _offenders(("render",), "door.style") == []
