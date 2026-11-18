"""`export` and `import`: carry profile/ and jobs/ to another computer as one archive.

The archive is a `.tar.gz` holding `manifest.json`, `profile/...` and `jobs/...`; the cores that pack and
unpack it are in `door.core.archive`.
`import` replaces the local data, after moving it to `backups/<timestamp>/`.

`connect`, `sync` and `disconnect` keep the same archive on Google Drive (issue #265,
`door.core.drive` and `door.core.sync`).
"""

import sys
from pathlib import Path

import click

from door.commands import _common as common
from door.core import archive as archive_core
from door.core import drive, lock, sync, workspace
from door.core.lock import SyncConflict


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
@click.group("data")
def data_group():
    """Move profile/ and jobs/ between computers (an archive or Google Drive); save a problem report."""


@click.command("export")
@click.argument("path", required=False, default=None, type=click.Path())
def export(path):
    """Pack profile/ and jobs/ into one archive to carry to another computer.

    PATH is the archive to write, or a directory to write
    door-export-<date>.tar.gz into (default: the current directory).
    """
    try:
        result = archive_core._export_core(path, profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR)
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    console = common._console()
    console.print()
    common._mark_line(console, "ok", "Exported profile/ and jobs/")
    console.print()
    _rows(console, [("Files", str(result["files"])), ("Size", _size(result["bytes"]))])
    _path_row(console, "Archive", result["path"])
    console.print()
    common._next_steps(console, [(f"./door data import {Path(result['path']).name}", "on the other computer")])


def _size(n: int) -> str:
    """``12.3 MB``, or ``45 KB`` under a megabyte."""
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{max(1, round(n / 1e3))} KB"


def _rows(console, rows: list[tuple[str, str]]) -> None:
    """``  Label    value`` lines, aligned with `_common._next_steps`."""
    from rich.markup import escape

    for label, value in rows:
        console.print(f"  [dim]{label:<8}[/] {escape(value)}", soft_wrap=True)


def _path_row(console, label: str, path: str) -> None:
    """A path on one line, never wrapped, so it stays copyable."""
    from rich.markup import escape

    console.print(f"  [dim]{label:<8}[/] [green]{escape(common._display_path(path))}[/]", soft_wrap=True)


def _err_console():
    """`_common._console` for stderr: colour only when stderr is a terminal."""
    from rich.console import Console

    return Console(stderr=True, force_terminal=sys.stderr.isatty(), highlight=False)


@click.command("import")
@click.argument("archive", type=click.Path())
def import_data(archive):
    """Replace profile/ and jobs/ with an archive made by `data export`.

    The current profile/ and jobs/ are moved to backups/<timestamp>/ first.
    """
    try:
        result = archive_core._import_core(archive, profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    console = common._console()
    console.print()
    common._mark_line(console, "ok", f"Imported {result['files']} files from {_markup_escape(common._display_path(result['archive']))}")
    console.print()
    _path_row(console, "Profile", result["profile_dir"])
    _path_row(console, "Jobs", result["jobs_dir"])
    if result["backup_dir"]:
        _path_row(console, "Backup", result["backup_dir"])
        _rows(console, [("", "your previous data, in case you need it back")])
    if result["warnings"]:
        err = _err_console()
        err.print()
        for warning in result["warnings"]:
            common._mark_line(err, "warn", _markup_escape(warning))
    console.print()
    common._next_steps(console, [("./door doctor", "check this computer has what The other door needs")])


def _markup_escape(text: str) -> str:
    from rich.markup import escape

    return escape(text)


# --------------------------------------------------------------------------- Google Drive
def _connect_core(show_url=None) -> dict:
    """Authorise The other door to its own folder on Google Drive (a browser opens once). Never prints.

    Returns:
        ``{"account"}``.

    Raises:
        drive.DriveError: not configured in this build, denied, no answer.
    """
    return drive.connect(show_url=show_url)


@lock.locked("sync")
def _sync_core(keep_local: bool = False, keep_drive: bool = False, *, jobs_dir: Path | None = None) -> dict:
    """Bring this computer and Google Drive level. Never prints.

    Returns:
        ``{"action": "push" | "pull" | "nothing" | "skipped", ...}``.

    Raises:
        ValueError: both `keep_local` and `keep_drive`.
        SyncConflict: both sides changed and neither flag was given.
        drive.DriveError: not connected, offline, revoked.
    """
    if keep_local and keep_drive:
        raise ValueError("choose one of keep_local and keep_drive, not both")
    return sync.sync_now(keep_local=keep_local, keep_drive=keep_drive)


def _disconnect_core() -> dict:
    """Forget this computer's Drive connection; the archive on Drive stays. Never prints.

    Returns:
        ``{"disconnected"}``: False when it was not connected.
    """
    return {"disconnected": drive.disconnect()}


def _fail(exc: Exception) -> None:
    click.echo(f"Error: {exc}", err=True)
    sys.exit(1)


@click.command("connect")
def connect():
    """Connect this computer to your Google Drive (once; a browser opens).

    The other door then keeps profile/ and jobs/ as one archive in My Drive/The other door/ and
    syncs it around every command that writes. It can see only what it created.
    """
    try:
        result = _connect_core(show_url=_show_sign_in_link)
    except (drive.DriveError, SyncConflict) as exc:
        _fail(exc)
    console = common._console()
    console.print()
    common._mark_line(console, "ok", f"Connected to Google Drive as {_markup_escape(result['account'])}")
    console.print()
    common._next_steps(console, [("./door data sync", "push or pull now (otherwise it happens by itself)")])


def _show_sign_in_link(url: str) -> None:
    click.echo("A browser opens to sign in to Google. If it doesn't, or Google loops or shows an")
    click.echo("error page, open this link in a private window:")
    click.echo(f"\n  {url}\n")


@click.command("sync")
@click.option("--keep-local", "keep_local", is_flag=True, help="After a both-sides change: replace Drive with this computer's data.")
@click.option("--keep-drive", "keep_drive", is_flag=True, help="After a both-sides change: replace this computer's data with Drive's.")
def sync_command(keep_local, keep_drive):
    """Push or pull now, whichever is needed; refuses when both sides changed."""
    if keep_local and keep_drive:
        raise click.UsageError("choose one of --keep-local and --keep-drive, not both")
    try:
        result = _sync_core(keep_local, keep_drive)
    except (drive.DriveError, SyncConflict, ValueError) as exc:
        _fail(exc)
    messages = {
        "push": "Pushed this computer's data to Google Drive",
        "pull": "Pulled newer data from Google Drive (yours is in backups/)",
        "nothing": "Already in step with Google Drive: nothing to do",
        "skipped": "Nothing to push yet: there is no profile/config.json",
    }
    common._mark_line(common._console(), "ok", messages[result["action"]])
    for warning in result.get("warnings", []):
        common._mark_line(_err_console(), "warn", _markup_escape(warning))


@click.command("disconnect")
def disconnect():
    """Forget this computer's Google Drive connection (the archive on Drive stays)."""
    result = _disconnect_core()
    common._mark_line(
        common._console(), "ok",
        "Disconnected from Google Drive" if result["disconnected"] else "Not connected to Google Drive",
    )
