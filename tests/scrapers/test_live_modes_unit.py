"""Every site, feed platform and discovery source has a live test for each mode that applies to it (#19).

A site's live tests are `tests/scrapers/<kind>/test_<name>_live.py`, one test per mode, named
`test_<name>_<mode>_live`:

- ``listing``: page 1 (`probe`), the field contract on its postings (every site);
- ``page2``: one more listing page still parses, unless the file says why there is none (``NO_PAGE2 = "..."``:
  one answer lists every job);
- ``details``: at most two detail pages still parse, unless the file says why there are none (``NO_DETAILS =
  "..."``: the listing carries the whole ad);
- ``zero_hits``: a board's zero-hit answer (`live_matrix.ZERO_HIT_FIXTURES`, or a reason in ``NO_ZERO_HIT``);
- ``detection``: a feed platform's careers page (`live_employers.DETECTION`, or a reason in ``NO_DETECTION``);
- ``employers``: a discovery source's search; ``lookthrough``: what a detect-only platform's look-through rests on.

No other test is in such a file, so the weekly run stays probe-sized, and the listing, page 2 and details tests
count their requests (`live_utils.probe_sized`) and check the fields (`live_utils.assert_contract`).
"""

import ast
import re

import pytest

from door.core import ats_detect, discovery_sources, sites
from live_employers import DETECTION, NO_DETECTION
from live_matrix import NO_LIVE_TEST, NO_ZERO_HIT, ZERO_HIT_FIXTURES
from paths import TESTS_DIR

MODES = ("listing", "page2", "details", "zero_hits", "detection", "employers", "lookthrough")
_OPTIONAL = {"page2": "NO_PAGE2", "details": "NO_DETAILS"}
_SCRAPERS = TESTS_DIR / "scrapers"


def _file(name: str):
    found = list(_SCRAPERS.rglob(f"test_{name}_live.py"))
    assert len(found) == 1, f"{name}: no live test file (or more than one): {found}"
    return found[0]


def _tests_and_reasons(name: str) -> tuple[set[str], dict[str, str], str]:
    path = _file(name)
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    tests = {node.name for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")}
    reasons = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    reasons[target.id] = node.value.value
    return tests, reasons, text


def _modes(name: str) -> set[str]:
    """The modes that apply to *name* before a file's own reasons are read."""
    if name in discovery_sources.SOURCES:
        return {"employers"}
    if name not in sites.SITES:  # a platform The other door only detects
        return {"detection"} if name not in NO_DETECTION else set()
    modes = {"listing", "page2", "details"}
    if sites.SITES[name].board and name not in NO_ZERO_HIT:
        modes.add("zero_hits")
    if name in ats_detect.PRECEDENCE and name not in NO_DETECTION:
        modes.add("detection")
    return modes


_NAMES = sorted({*sites.SITES, *ats_detect.PRECEDENCE, *discovery_sources.SOURCES} - set(NO_LIVE_TEST))


@pytest.mark.parametrize("name", _NAMES)
def test_each_mode_that_applies_has_its_live_test(name):
    tests, reasons, _ = _tests_and_reasons(name)
    missing = []
    for mode in sorted(_modes(name)):
        if f"test_{name}_{mode}_live" in tests:
            continue
        if mode in _OPTIONAL and (reasons.get(_OPTIONAL[mode]) or "").strip():
            continue
        missing.append(mode)
    assert not missing, f"{name}: no live test for {missing} (test_{name}_<mode>_live, or a reason in " \
                        f"{[_OPTIONAL[m] for m in missing if m in _OPTIONAL]})"


@pytest.mark.parametrize("name", _NAMES)
def test_a_live_file_holds_only_its_modes(name):
    tests, reasons, _ = _tests_and_reasons(name)
    named = re.compile(rf"^test_{re.escape(name)}_({'|'.join(MODES)})_live$")
    assert {t for t in tests if not named.match(t)} == set()
    for mode, constant in _OPTIONAL.items():
        assert not (constant in reasons and f"test_{name}_{mode}_live" in tests), f"{name}: {constant} and a {mode} test"


@pytest.mark.parametrize("name", sorted(n for n in sites.SITES if n not in NO_LIVE_TEST))
def test_the_page_tests_count_their_requests_and_check_the_fields(name):
    tests, _, text = _tests_and_reasons(name)
    if tests & {f"test_{name}_{m}_live" for m in ("listing", "page2", "details")}:
        assert any(f in text for f in ("probe_sized(", "assert_listing(")), f"{name}: requests not counted"
        assert any(f in text for f in ("assert_contract(", "assert_listing(", "assert_page2(")), f"{name}: no field contract"


def test_the_tables_name_only_what_exists():
    assert set(DETECTION) | set(NO_DETECTION) == set(ats_detect.PRECEDENCE)
    assert not set(DETECTION) & set(NO_DETECTION)
    assert set(ZERO_HIT_FIXTURES) | set(NO_ZERO_HIT) == {n for n, s in sites.SITES.items() if s.board}
