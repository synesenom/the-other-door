"""`data report`: one archive to send when something went wrong (#593).

There is no backend: the user saves the archive and sends it to whoever helps them. It holds the
problem log (`logs/door.log*`, `door.core.problem_log`), the last `RUNS_KEPT` run records cut to their
counts, outcomes and errors, doctor's checks, and the version and OS. Every text in it is masked
(emails, the data folder, the home folder); nothing from profile/, no postings, no ledger.
"""

import json
import os
import platform
import re
import sys
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import click

from door import version as version_mod
from door.commands import _common as common
from door.commands import setup as setup_cmd
from door.core import problem_log, recurring, workspace

RUNS_KEPT = 5

_README = """\
A problem report from The other door, made {made_at}.

What is in it:
  logs/       what went wrong lately: failed tool calls, sites that failed, ads left unscored,
              warnings and crashes (one line each, no CV, profile or ad text)
  runs/       the last {runs} runs: counts, outcomes and errors only
  doctor.json the checks of this computer (what is installed, signed in, configured)
  about.json  the version of The other door, the operating system and Python

What is not: your CV, your profile, the job ads, your applications. Emails are replaced by
<email>, the data folder by <data folder> and your home folder by ~.
"""

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# What a run record keeps: per step block its numbers, its summary and these lists, cut to these fields.
_SITE_FIELDS = ("site", "outcome", "count", "stale", "non_local", "errors", "error", "warning", "until")
_RECORD_FIELDS = ("started_at", "finished_at", "elapsed_s", "steps", "skipped", "failures")
_STEPS = ("search", "discover", "follow", "collect", "match")


def _default_name() -> str:
    return f"door-report-{date.today().isoformat()}.zip"


def _spellings(folder) -> set[str]:
    """The ways a folder may be written: as given, resolved, and on macOS with or without `/private`."""
    found = {str(folder), str(Path(folder).expanduser().resolve())}
    found |= {s.removeprefix("/private") for s in found if s.startswith("/private/")}
    return {s for s in found if len(s) > 1}


def _masker():
    """A function that hides emails, the data folder (``<data folder>``) and the home folder (``~``) in a text."""
    data_folders = [workspace.HOME] + ([os.environ["DOOR_HOME"]] if os.environ.get("DOOR_HOME") else [])
    places = []
    for folders, word in ((data_folders, "<data folder>"), ([Path.home()], "~")):
        for folder in folders:
            places += [(spelling, word) for spelling in _spellings(folder)]
    places.sort(key=lambda p: len(p[0]), reverse=True)  # the longest first: the data folder is often inside home

    def mask(text: str) -> str:
        for spelling, word in places:
            text = text.replace(spelling, word)
        return _EMAIL.sub("<email>", text)

    return mask


def _trim_block(block):
    if not isinstance(block, dict):
        return block
    kept = {k: v for k, v in block.items() if isinstance(v, (int, float, bool)) or k in ("summary", "skipped")}
    if isinstance(block.get("sites"), list):
        kept["sites"] = [{k: e[k] for k in _SITE_FIELDS if k in e} for e in block["sites"] if isinstance(e, dict)]
    if isinstance(block.get("failures"), list):  # match: the unscored ads, by id, with why
        kept["failures"] = [{"id": f.get("id"), "error": f.get("error")} for f in block["failures"] if isinstance(f, dict)]
    return kept


def _trim_record(record: dict) -> dict:
    """A run record without titles, companies, folders or anything else of the ads: counts, outcomes, errors."""
    trimmed = {k: record[k] for k in _RECORD_FIELDS if k in record}
    for step in _STEPS:
        if step in record:
            trimmed[step] = _trim_block(record[step])
    return trimmed


def _doctor(profile_dir: Path, jobs_dir: Path) -> dict:
    try:
        report = setup_cmd._doctor_core(profile_dir, jobs_dir)
    except Exception as exc:  # noqa: BLE001 - the report is wanted most when something is broken
        return {"error": f"{type(exc).__name__}: {exc}"}
    checks = [{k: c.get(k) for k in ("name", "status", "required", "detail")} for c in report.get("checks") or []]
    return {"ok": report.get("ok"), "checks": checks, "last_run": report.get("last_run")}


def _target(path) -> Path:
    target = Path(path).expanduser() if path else Path.cwd()
    if target.is_dir():
        target = target / _default_name()
    elif target.suffix.lower() != ".zip":
        target = target.with_name(target.name + ".zip")
    if target.exists():
        raise FileExistsError(f"{target} already exists — pass another path")
    return target


def _report_core(path: Path | str | None = None, *, profile_dir: Path | None = None, jobs_dir: Path | None = None) -> dict:
    """Write the problem report, one `.zip`. Never prints; writes nothing but the archive and the time it
    was saved (`recurring.stamp_report`: the app's "Something keeps going wrong" line goes away).

    Args:
        path: The archive to write (``.zip`` is added when missing), or a directory to write
            ``door-report-<date>.zip`` into. Default: the current directory.

    Returns:
        ``{"path", "files": [names in the archive], "bytes"}``.

    Raises:
        FileExistsError: the archive already exists.
    """
    profile_dir = workspace.PROFILE_DIR if profile_dir is None else profile_dir
    jobs_dir = workspace.JOBS_DIR if jobs_dir is None else jobs_dir
    target = _target(path)
    mask = _masker()
    made_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    entries: dict[str, str] = {"README.txt": _README.format(made_at=made_at, runs=RUNS_KEPT)}
    entries["about.json"] = json.dumps({
        "version": version_mod.VERSION,  # the desktop app's too: one version (#224)
        "os": platform.platform(),
        "python": platform.python_version(),
        "from_checkout": workspace.is_checkout(),
        "made_at": made_at,
    }, indent=2)
    entries["doctor.json"] = json.dumps(_doctor(profile_dir, jobs_dir), indent=2, ensure_ascii=False)
    logs = workspace.HOME / problem_log.FOLDER
    for log in sorted(logs.glob(problem_log.FILE + "*")) if logs.is_dir() else ():
        entries[f"logs/{log.name}"] = log.read_text(encoding="utf-8", errors="replace")
    runs_dir = Path(jobs_dir) / "runs"
    for record_path in sorted(runs_dir.glob("*.json"))[-RUNS_KEPT:] if runs_dir.is_dir() else ():
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict):
            entries[f"runs/{record_path.name}"] = json.dumps(_trim_record(record), indent=2, ensure_ascii=False)

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, text in entries.items():
                archive.writestr(name, mask(text))
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    recurring.stamp_report(workspace.HOME)  # what went wrong before it is in the report: said no more
    return {"path": str(target), "files": list(entries), "bytes": target.stat().st_size}


@click.command("report")
@click.argument("path", required=False, default=None, type=click.Path())
def report(path):
    """Save a problem report to send to whoever helps you with The other door.

    It holds what went wrong lately (logs/door.log), the last runs' counts and errors, the
    checks of this computer and the versions; no CV, profile, ads or applications, and emails
    and home folders are masked. PATH is the .zip to write, or a directory to write
    door-report-<date>.zip into (default: the current directory).
    """
    try:
        result = _report_core(path)
    except FileExistsError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    console = common._console()
    console.print()
    common._mark_line(console, "ok", "Saved a problem report")
    console.print()
    from rich.markup import escape

    console.print(f"  [dim]{'Report':<8}[/] [green]{escape(common._display_path(result['path']))}[/]", soft_wrap=True)
    console.print()
    console.print("  Send it to the person who helps you with The other door. It holds no CV, profile, ads or applications.")
