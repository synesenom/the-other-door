"""Guard: the lower packages never import the command layer (issue #357).

`door.commands` composes the packages below it; `render/` has no business reaching up
into it. `pipeline/` is left out: it is the layer that composes
the commands' cores (`find`'s five steps). There is no exception: `core/sync/sync.py`'s Drive hooks call the
archive cores in `core/sync/archive.py`. Nor do they import `door.pipeline`.
"""

import ast

from paths import PACKAGE_DIR

LOWER = ("render", "core", "tailoring", "matching", "i18n", "scrapers")


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


def test_employers_sync_and_downloads_never_import_jobs_or_phone():
    below = ("core/employers", "core/sync", "core/downloads")
    assert _offenders(below, "door.core.jobs") == set()
    assert _offenders(below, "door.core.phone") == set()


def test_jobs_never_imports_phone_or_sync():
    assert _offenders(("core/jobs",), "door.core.phone") == set()
    assert _offenders(("core/jobs",), "door.core.sync") == set()


def test_phone_never_imports_sync():
    assert _offenders(("core/phone",), "door.core.sync") == set()
