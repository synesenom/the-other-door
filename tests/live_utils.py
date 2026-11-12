"""Helpers for the live smoke tests.

Some sites and APIs do not answer from GitHub's runners. In CI (`CI` set), a
live test whose site came back empty *with recorded errors* is skipped, not failed: the status page then keeps
the site's last result (❓). Locally it still fails, and an empty answer with no errors (a silent site change)
fails everywhere.
"""

import os

import pytest


def in_ci() -> bool:
    return bool(os.environ.get("CI"))


def skip_if_refused_in_ci(site: str, errors: list) -> None:
    """Skip the test in CI when *site* recorded errors (a refusal of the runner's IP, most likely)."""
    if in_ci() and errors:
        pytest.skip(f"{site} refused the CI runner: {errors[:3]}")
