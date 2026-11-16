"""CLI journeys (#33): see tests/cli_world.py. Everything here but the `_unit` tests is marked `cli_journeys`."""

from pathlib import Path

import pytest

HERE = Path(__file__).parent


def pytest_collection_modifyitems(items):
    # The hook sees every item of the session, so only the ones under this folder are marked (#180).
    for item in items:
        path = Path(str(item.path))
        if HERE not in path.parents or path.name.endswith("_unit.py"):
            continue
        item.add_marker(pytest.mark.cli_journeys)
