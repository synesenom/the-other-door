"""A packaged app runs door from a read-only bundle (#223): `src/`, `.claude/agents/` and `profile.example/`
copied into the app, the data in the user's folder. Nothing may be written inside the bundle."""

import json
import os
import shutil
import subprocess
import sys

import pytest

from paths import REPO_ROOT

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="read-only folders are not enforced for root, and chmod differs on Windows",
)

_SCRIPT = """
import json
from door.commands import profile as p, setup as s
from door.core import workspace
report = s._doctor_core(profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR, probe=False)
fields = p._profile_fields(name="Ada", email="ada@example.com", location="Aarhus", role_targets=["Data Analyst"], remote="hybrid")
p._init_core(fields, profile_dir=workspace.PROFILE_DIR, example_dir=workspace.PROFILE_EXAMPLE_DIR)
mcp = workspace.ensure_mcp_config()
agent = (workspace.REPO_ROOT / ".claude" / "agents" / "matcher.md").read_text()
print(json.dumps({"checks": [c["name"] for c in report["checks"]], "checkout": workspace.is_checkout(),
                  "mcp": str(mcp), "home": str(workspace.HOME), "agent": len(agent) > 0}))
"""


def _snapshot(root):
    return sorted((str(p.relative_to(root)), p.stat().st_mtime_ns) for p in root.rglob("*"))


def test_door_runs_from_a_read_only_bundle_and_writes_only_to_its_home(tmp_path):
    bundle = tmp_path / "Resources" / "door"
    shutil.copytree(REPO_ROOT / "src", bundle / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (bundle / ".claude" / "agents").mkdir(parents=True)
    for agent in ("tailor.md", "matcher.md"):
        shutil.copy(REPO_ROOT / ".claude" / "agents" / agent, bundle / ".claude" / "agents" / agent)
    shutil.copytree(REPO_ROOT / "profile.example", bundle / "profile.example")
    for path in [bundle, *bundle.rglob("*")]:
        path.chmod(0o555 if path.is_dir() else 0o444)
    before = _snapshot(bundle)
    home, user = tmp_path / "data", tmp_path / "user"
    user.mkdir()
    env = {
        "PYTHONPATH": str(bundle / "src"), "DOOR_HOME": str(home), "HOME": str(user),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PATH": "/usr/bin:/bin",
    }
    try:
        out = subprocess.run([sys.executable, "-s", "-c", _SCRIPT], env=env, cwd=bundle, capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr
        result = json.loads(out.stdout.strip().splitlines()[-1])
        assert result["checkout"] is False
        assert "dev dependencies" not in result["checks"]
        assert result["home"] == str(home.resolve())
        assert result["mcp"] == str(home.resolve() / ".mcp.json")
        assert result["agent"] is True
        assert (home / "profile" / "config.json").is_file()
        assert _snapshot(bundle) == before
    finally:
        for path in [bundle, *bundle.rglob("*")]:
            path.chmod(0o755 if path.is_dir() else 0o644)
