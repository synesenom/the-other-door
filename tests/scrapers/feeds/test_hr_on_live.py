"""Live smoke test for HR-ON: detect-only, so it checks that a real employer's careers page is still
recognised as one (#19). Opt-in: run with `./scripts/run-test.sh --live`.
"""

import pytest

from live_utils import assert_detects


@pytest.mark.live
def test_hr_on_detection_live():
    """A real employer's careers page still shows hr_on and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("hr_on")
