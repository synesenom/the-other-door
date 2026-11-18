"""Guard: the lower packages never import the command layer (issue #357).

`door.commands` composes the packages below it; `render/` and `style/` have no business reaching up
into it, and `render/` is also under `style/`. `pipeline/` is left out: it is the layer that composes
the commands' cores (`find`'s five steps). There is no exception: `core/sync/sync.py`'s Drive hooks call the
archive cores in `core/sync/archive.py`. Nor do they import `door.pipeline`.
"""

import ast

from paths import PACKAGE_DIR

LOWER = ("render", "style", "core", "tailoring", "matching", "i18n", "scrapers")


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            for alias in node.names:
                yield node.lineno, f"{node.module}.{alias.name}"


def _offenders(packages, forbidden):
    found = set()
    for package in packages:
        for path in sorted((PACKAGE_DIR / package).rglob("*.py")):
            for _line, name in _imports(path):
                if name == forbidden or name.startswith(forbidden + "."):
                    found.add((str(path.relative_to(PACKAGE_DIR)), name))
    return found


def test_the_lower_packages_never_import_the_commands():
    assert _offenders(LOWER, "door.commands") == set()


def test_the_lower_packages_never_import_the_pipeline():
    assert _offenders(LOWER, "door.pipeline") == set()


def test_render_never_imports_style():
    assert _offenders(("render",), "door.style") == set()
