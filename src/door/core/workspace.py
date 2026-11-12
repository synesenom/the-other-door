"""Where The other door keeps its data: the repo root (the code, `profile.example/`, `.claude/`), and the data
folder `HOME` (`$DOOR_HOME`, the repo root when unset) with `profile/`, `jobs/`, `backups/`, `upskill/`
and a generated `.mcp.json`; and where in `jobs/` the postings go: `jobs/postings/<YYYY-MM-DD>/<site>/`, apart from the ledgers.

Commands read these at call time (`workspace.JOBS_DIR`), so tests can point them at a
temporary directory with `monkeypatch.setattr(workspace, "JOBS_DIR", ...)`.
"""

import json
import os
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]   # src/door/core/workspace.py -> the repo
# The data folder, read once at import: `$DOOR_HOME`, else the checkout (empty = unset).
HOME = Path(os.environ.get("DOOR_HOME") or REPO_ROOT).expanduser().resolve()
PROFILE_DIR = HOME / "profile"
PROFILE_EXAMPLE_DIR = REPO_ROOT / "profile.example"   # ships with the code
JOBS_DIR = HOME / "jobs"
BACKUPS_DIR = HOME / "backups"   # what `import` replaced, one folder per import
UPSKILL_DIR = HOME / "upskill"   # `skill-gaps` / `/upskill` reports
MCP_CONFIG = HOME / ".mcp.json"   # the checkout's committed file, or the one `ensure_mcp_config` writes

def mcp_config_entry() -> dict:
    """The `.mcp.json` content that starts the door server with the interpreter running now."""
    env = {"PYTHONPATH": str(REPO_ROOT / "src"), "DOOR_HOME": str(HOME)}
    if os.environ.get("DOOR_BIN"):  # the packaged app's bundled Tectonic, for the tailor's compile
        env["DOOR_BIN"] = os.environ["DOOR_BIN"]
    return {"mcpServers": {"door": {
        "command": sys.executable,
        "args": ["-m", "door.mcp_server"],
        "env": env,
    }}}


def is_checkout() -> bool:
    """Run from the git checkout (a developer's), not from a packaged app's read-only bundle (#223)."""
    return (REPO_ROOT / "pyproject.toml").is_file()


def ensure_mcp_config() -> Path:
    """The `.mcp.json` the tailor session uses.

    With the default home that is the checkout's committed file, untouched. With a custom
    `DOOR_HOME` it is generated there for this interpreter, rewritten when it names another.
    """
    if HOME == REPO_ROOT:
        return MCP_CONFIG
    wanted = mcp_config_entry()
    try:
        if json.loads(MCP_CONFIG.read_text(encoding="utf-8")) == wanted:
            return MCP_CONFIG
    except (OSError, ValueError):
        pass
    tmp = MCP_CONFIG.with_name(MCP_CONFIG.name + f".{os.getpid()}.tmp")
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(wanted, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, MCP_CONFIG)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"cannot write {MCP_CONFIG} ({exc}); DOOR_HOME must be a writable folder") from None
    return MCP_CONFIG


POSTINGS = "postings"   # jobs/postings/<YYYY-MM-DD>/<site>/<job_id>.json
DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def postings_dir(jobs_dir: Path) -> Path:
    """The folder that holds a day folder per scrape date."""
    return Path(jobs_dir) / POSTINGS


def day_dir(jobs_dir: Path, day: str) -> Path:
    """The folder of one day's postings, ``jobs/postings/<day>/``."""
    return postings_dir(jobs_dir) / day


def move_day_folders(jobs_dir: Path) -> int:
    """Move the day folders an older version left directly under *jobs_dir* into `postings_dir`.

    A day already there is merged file by file, the file already in `postings_dir` winning; the
    old folder goes once it is empty. Returns how many day folders were found. Idempotent.
    """
    jobs_dir = Path(jobs_dir)
    if not jobs_dir.is_dir():
        return 0
    old = [d for d in sorted(jobs_dir.iterdir()) if d.is_dir() and DAY_RE.fullmatch(d.name)]
    for day in old:
        target = day_dir(jobs_dir, day.name)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            day.rename(target)
            continue
        for file in sorted(p for p in day.rglob("*") if p.is_file()):
            dest = target / file.relative_to(day)
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                file.rename(dest)
        for folder in sorted((p for p in day.rglob("*") if p.is_dir()), reverse=True):
            if not any(folder.iterdir()):
                folder.rmdir()
        if not any(day.iterdir()):
            day.rmdir()
    return len(old)
