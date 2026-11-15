"""CLI journeys (#33): see tests/cli_world.py. Everything here but the `_unit` tests is marked `cli_journeys`."""

import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        if item.nodeid.split("::")[0].endswith("_unit.py"):
            continue
        item.add_marker(pytest.mark.cli_journeys)
