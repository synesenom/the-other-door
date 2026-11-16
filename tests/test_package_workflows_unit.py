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
    builders = {name for name, job in jobs.items()
                if any(s.get("run") == "npm run package" for s in job.get("steps", []))}
    tested = {name for name, job in jobs.items() if any("test:install" in str(s.get("run", "")) for s in job["steps"])}
    assert tested == {"windows", "windows-arm"} and not builders & tested
    for name in tested:
        assert set([jobs[name]["needs"]] if isinstance(jobs[name]["needs"], str) else jobs[name]["needs"]) == builders
    assert any("test:package" in str(s.get("run", "")) for s in jobs["windows"]["steps"])
