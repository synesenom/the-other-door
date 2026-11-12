"""Import guard: a site module's only `door` import is `door.scrapers.sdk`.

The discovery sources (`core/discovery_sources.SOURCES`: `linkedin`, which is not a `Site`) are
scanned the same way (#280)."""
import ast

import pytest

from door.core import discovery_sources
from door.core.sites import SITES
from tests.paths import REPO_ROOT



def _path(name: str):
    """The module file of a site or discovery source, wherever its registry entry puts it."""
    dotted = SITES[name].module if name in SITES else discovery_sources.SOURCES[name]
    return REPO_ROOT / "src" / (dotted.replace(".", "/") + ".py")


def _foreign_imports(path) -> list[str]:
    """Every `door` import in the file (nested ones too) that is not the SDK."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] == "door" and a.name != "door.scrapers.sdk"]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.append("." * node.level + (node.module or ""))
            elif node.module == "door.scrapers.sdk":
                continue
            elif node.module == "door.scrapers" and all(a.name == "sdk" for a in node.names):
                continue
            elif (node.module or "").split(".")[0] == "door":
                found.append(node.module)
    return found


@pytest.mark.parametrize("site", sorted({*SITES, *discovery_sources.SOURCES}))
def test_a_site_module_imports_door_only_through_the_sdk(site):
    extra = _foreign_imports(_path(site))
    assert not extra, f"{site} imports {extra}; import from door.scrapers.sdk instead"


def test_every_discovery_source_module_is_scanned():
    scanned = {*SITES, *discovery_sources.SOURCES}
    assert set(discovery_sources.SOURCES) <= scanned
    for name, dotted in discovery_sources.SOURCES.items():
        assert dotted == f"door.scrapers.discovery.{name}" and _path(name).exists()


def test_the_scanner_sees_nested_and_plain_imports(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("import door.core.x\nfrom door import i18n\nfrom door.scrapers import sdk, report\n"
                 "from door.scrapers.sdk import report\n\ndef g():\n    from door.scrapers import probe_failure\n"
                 "    from . import y\n")
    assert _foreign_imports(f) == ["door.core.x", "door", "door.scrapers", "door.scrapers", "."]
