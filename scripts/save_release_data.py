"""Save a release's own data and what it read back, as the sample of the release gate (#57).

    poetry run python scripts/save_release_data.py X.Y.Z

Checks out the tag `vX.Y.Z` in a throwaway git worktree and runs, with that tag's `src/` on PYTHONPATH and a
temporary home as `DOOR_HOME`, `release_data_generate.py` (the tag's own code writes a small `profile/` and `jobs/` of
made-up data) and then `release_data.py snapshot` (the tag's own tools read it back). `profile/`, `jobs/` and
`expected.json` are copied to `tests/data_versions/X.Y.Z/` and the worktree is removed. The gate
(`tests/release/test_release_data.py`) opens each saved folder with the current code and compares.

No network, no `claude`: the generator writes through the release's stores and cores. `HOME`, `XDG_CONFIG_HOME` and
`APPDATA` point into the temporary folder, so the release never reaches a real Google Drive or config. `/dev-release`
runs it after the tag exists and commits the result; a tag whose API the generator does not know fails loudly.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SAMPLES = REPO / "tests" / "data_versions"
SCRIPTS = REPO / "scripts"


def run(cmd: list[str], *, cwd: Path, env: dict | None = None) -> str:
    done = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if done.returncode != 0:
        sys.stderr.write(done.stdout + done.stderr)
        raise SystemExit(f"failed: {' '.join(cmd[:4])} ... (exit {done.returncode})")
    return done.stdout


def save(version: str) -> Path:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"{version!r} is not a version: give X.Y.Z")
    tag = f"v{version}"
    run(["git", "rev-parse", "--verify", f"refs/tags/{tag}"], cwd=REPO)
    target = SAMPLES / version
    if target.exists():
        raise SystemExit(f"{target} exists: delete it first to save it again")
    with tempfile.TemporaryDirectory(prefix="door-release-") as scratch:
        scratch = Path(scratch)
        tree, home = scratch / "tree", scratch / "home"
        home.mkdir()
        run(["git", "worktree", "add", "--detach", str(tree), tag], cwd=REPO)
        try:
            env = {
                **os.environ,
                "PYTHONPATH": str(tree / "src"),
                "DOOR_HOME": str(home),
                "HOME": str(scratch / "userhome"),
                "XDG_CONFIG_HOME": str(scratch / "config"),
                "APPDATA": str(scratch / "config"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            env.pop("PYTHONHOME", None)
            for key in ("ANTHROPIC_API_KEY", "DOOR_BIN"):
                env.pop(key, None)
            run([sys.executable, str(SCRIPTS / "release_data_generate.py")], cwd=tree, env=env)
            # The first read renders the page images `show` makes when they are missing (and says so, `rendered`);
            # the second is what the release answers from then on, and is the snapshot.
            run([sys.executable, str(SCRIPTS / "release_data.py"), "snapshot", str(home)], cwd=tree, env=env)
            expected = run([sys.executable, str(SCRIPTS / "release_data.py"), "snapshot", str(home)], cwd=tree, env=env)
        finally:
            run(["git", "worktree", "remove", "--force", str(tree)], cwd=REPO)
        target.mkdir(parents=True)
        for name in ("profile", "jobs"):
            shutil.copytree(home / name, target / name, ignore=shutil.ignore_patterns(".lock", ".lock.json", ".progress.json", "__pycache__"))
        (target / "expected.json").write_text(json.dumps(json.loads(expected), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write(__doc__.split("\n\n")[0] + "\n")
        return 2
    print(f"Saved {save(argv[0])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
