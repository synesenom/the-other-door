"""One Chromium pin (#165): `src/door/core/downloads/chromium_pin.json` is read by `doctor --fix`'s installer and by
the bundle scripts, so a version bump is one edit; the checks that exercise the bundle print a page."""

from __future__ import annotations

import json

from paths import REPO_ROOT

SCRIPTS = REPO_ROOT / "app" / "scripts"


def _text(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def test_bundle_lock_does_not_carry_a_second_chromium_pin():
    assert "chromium" not in json.loads(_text("bundle.lock.json"))


def test_the_unix_bundle_reads_the_one_pin_for_each_system_it_packages():
    sh = _text("bundle-python.sh")
    assert "chromium_pin.json" in sh
    for key in ("mac-arm64", "linux64"):
        assert key in sh
    assert "bin/chromium" in sh


def test_the_windows_bundle_reads_the_one_pin():
    ps1 = _text("bundle-python.ps1")
    assert "chromium_pin.json" in ps1 and "win64" in ps1
    assert r"bin\chromium" in ps1 or "'chromium'" in ps1


def test_check_bundle_runs_doctor_with_the_bundled_chromium():
    sh = _text("check-bundle.sh")
    assert 'by["chromium"]' in sh and "DOOR_BIN" in sh
