"""What the package workflows run on a pull request, and what only the release does (#136)."""

import yaml

from tests.paths import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _steps(name):
    return [s for job in _load(name)["jobs"].values() for s in job.get("steps", [])]


def test_the_mac_package_check_builds_the_dmg_only():
    package = [s for s in _steps("package-macos.yml") if s.get("run") == "npm run package"]
    assert package and all(s.get("env", {}).get("DOOR_DMG_ONLY") == "1" for s in package)


def test_the_release_still_builds_the_updater_zip():
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert "DOOR_DMG_ONLY" not in text


def test_the_release_runs_the_unit_tests_off_linux():
    runs = [s for s in _steps("release.yml") if "vitest run" in str(s.get("run", ""))]
    assert runs


def test_windows_on_arm_starts_once_the_installer_is_built():
    """The ARM install test waits for the installer, not for the x64 install tests (the slowest PR path)."""
    jobs = _load("package-windows.yml")["jobs"]
    assert jobs["windows-arm"]["needs"] == jobs["windows"]["needs"] == "build"


def test_every_packaging_check_still_runs_on_each_platform():
    for name in ("package-linux.yml", "package-macos.yml", "package-windows.yml"):
        runs = " ".join(str(s.get("run", "")) for s in _steps(name))
        assert "test:install" in runs and "test:package" in runs, name
    jobs = _load("package-windows.yml")["jobs"]
    uploaded = {s["with"]["name"] for s in jobs["build"]["steps"] if "upload-artifact" in str(s.get("uses"))}
    for name in ("windows", "windows-arm"):
        downloaded = {s["with"]["name"] for s in jobs[name]["steps"] if "download-artifact" in str(s.get("uses"))}
        assert downloaded and downloaded <= uploaded, name
