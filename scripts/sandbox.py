"""Run the real `door` CLI against a throwaway profile: real sites, your data untouched.

`<dir>/profile/` and `<dir>/jobs/` replace the repo's (the profile is copied from
`profile.example/` the first time), and the Google Drive sync is off, so nothing reaches
your own profile, ledgers or Drive archive. Everything else is real: the job sites are
fetched and `find match` scores with `claude -p` (keep `prescreen_top_n` small).
`/dev-add-country`'s validator uses it to try a new country's boards with a fake profile.

Usage:  poetry run python scripts/sandbox.py <dir> <door command ...>
   e.g. poetry run python scripts/sandbox.py thoughts/country/de/sandbox init --location Berlin
        poetry run python scripts/sandbox.py thoughts/country/de/sandbox find search --boards stepstone
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from door.core import lock, workspace  # noqa: E402


def install(sandbox: Path) -> None:
    """Point the workspace at *sandbox*, seed its profile once, and turn the Drive sync off."""
    workspace.HOME = sandbox
    workspace.PROFILE_DIR = sandbox / "profile"
    workspace.JOBS_DIR = sandbox / "jobs"
    workspace.BACKUPS_DIR = sandbox / "backups"
    workspace.UPSKILL_DIR = sandbox / "upskill"
    workspace.MCP_CONFIG = sandbox / ".mcp.json"
    if not workspace.PROFILE_DIR.exists():
        shutil.copytree(workspace.PROFILE_EXAMPLE_DIR, workspace.PROFILE_DIR)
        # A sandbox scores on purpose; the example CV itself is refused, so this is a changed copy.
        with (workspace.PROFILE_DIR / "cv.md").open("a", encoding="utf-8") as cv:
            cv.write("\n<!-- a sandbox's copy -->\n")
    workspace.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    # Never your Google Drive: the sync would treat the sandbox as the workspace and push it.
    lock.pre_acquire_hook = lambda purpose, jobs_dir: None
    lock.post_release_hook = lambda purpose, jobs_dir: None


def _cli():
    from door.cli import cli

    return cli.main


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write(__doc__.split("\n\n")[-1] + "\n")
        return 2
    install(Path(argv[0]).resolve())
    return _cli()(args=argv[1:], prog_name="door", standalone_mode=True) or 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
