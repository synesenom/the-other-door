"""The caches the pull-request workflows restore are the ones seed-caches.yml saves on main (#80).

A cache a pull request saves is scoped to that pull request; only caches saved on main are shared.
seed-caches.yml saves them there, so its keys must be the very keys the other workflows look up:
a key that drifts leaves the seed saving a cache nobody reads, and every run still green.
"""

import re

import pytest
import yaml

from tests.paths import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CONSUMERS = ["package-linux.yml", "package-macos.yml", "package-windows.yml", "release.yml", "tests.yml", "app.yml"]
_MATRIX = re.compile(r"\$\{\{\s*matrix\.(\w+)\s*\}\}")


def _caches(name: str) -> set[tuple[str, str]]:
    """Each (path, key) an actions/cache step of the workflow uses, one per matrix row it runs on."""
    workflow = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    found = set()
    for job in workflow["jobs"].values():
        rows = (job.get("strategy") or {}).get("matrix", {}).get("include") or [{}]
        for step in job.get("steps", []):
            if not str(step.get("uses", "")).startswith("actions/cache"):
                continue
            path, key = step["with"]["path"], step["with"]["key"]
            for row in rows:
                if "if" in step and "matrix.bundle" in step["if"] and not row.get("bundle"):
                    continue
                found.add((path, _MATRIX.sub(lambda m: str(row[m.group(1)]), key)))
    return found


@pytest.mark.parametrize("name", CONSUMERS)
def test_every_cache_a_workflow_restores_is_seeded_on_main(name):
    seeded = _caches("seed-caches.yml")
    missing = _caches(name) - seeded
    assert not missing, f"{name} restores caches seed-caches.yml never saves: {sorted(missing)}"


def test_the_seed_runs_on_every_runner_that_restores_npm():
    seed = yaml.safe_load((WORKFLOWS / "seed-caches.yml").read_text(encoding="utf-8"))
    seeded = {row["os"] for job in seed["jobs"].values() for row in (job.get("strategy") or {}).get("matrix", {}).get("include", [])}
    for name in CONSUMERS:
        workflow = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
        for job in workflow["jobs"].values():
            if not any(step.get("with", {}).get("cache") == "npm" for step in job.get("steps", [])):
                continue
            rows = (job.get("strategy") or {}).get("matrix", {}).get("include") or [{}]
            for row in rows:
                runner = _MATRIX.sub(lambda m: str(row[m.group(1)]), job["runs-on"])
                assert runner in seeded, f"{name} restores npm on {runner}, which seed-caches.yml does not run on"
