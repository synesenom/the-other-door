"""`export` and `import`: carry profile/ and jobs/ to another computer as one archive.

The archive is a `.tar.gz` holding `manifest.json`, `profile/...` and `jobs/...`.
The ledger lock never goes in it.
`import` replaces the local data, after moving it to `backups/<timestamp>/`.

`connect`, `sync` and `disconnect` keep the same archive on Google Drive (issue #265,
`door.core.drive` and `door.core.sync`).
"""

import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath

import click

from door.commands import _common as common
from door.core import drive, migrations, sync, usage, workspace
from door.core.lock import SyncConflict

# Bump when the archive layout changes; `import` refuses a newer format.
FORMAT = 1

_MANIFEST = "manifest.json"
# Never exported, kept in place on import: the lock files, and this computer's Claude usage log (#575).
_LOCK_FILES = (".lock", ".lock.json", ".progress.json", usage.LOG_NAME)
_EXCLUDED = {"profile": (), "jobs": _LOCK_FILES}

# Config keys holding a path that may only exist on the computer that exported.
_PATH_KEYS = ("cv_template", "cv_content", "cover_letter_template", "photo")

# Config keys that belong to one computer: left out of the archive, and an import keeps this computer's own.
_LOCAL_KEYS = ("claude_config_dir",)


def _default_name() -> str:
    return f"door-export-{date.today().isoformat()}.tar.gz"


def _read_config(path: Path) -> dict | None:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return config if isinstance(config, dict) else None


def _config_without_local_keys(path: Path) -> bytes | None:
    """The config's bytes minus `_LOCAL_KEYS`, or None when it has none (or cannot be read): then the file goes as it is."""
    config = _read_config(path)
    if config is None or not any(k in config for k in _LOCAL_KEYS):
        return None
    for key in _LOCAL_KEYS:
        config.pop(key, None)
    return (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _keep_local_keys(staged: Path, old: Path) -> None:
    """Carry this computer's `_LOCAL_KEYS` from its config (`old`) into the imported one (`staged`)."""
    mine = _read_config(old)
    theirs = _read_config(staged)
    if mine is None or theirs is None:
        return
    kept = {k: mine[k] for k in _LOCAL_KEYS if k in mine}
    if kept:
        staged.write_text(json.dumps({**theirs, **kept}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _add_tree(tar: tarfile.TarFile, root: Path, arcname: str, exclude: tuple[str, ...]) -> int:
    """Add every regular file under `root` as `<arcname>/<relative path>`; return the count.

    Top-level entries named in `exclude` are skipped, and so are symlinks. The profile's
    config.json goes without the keys of `_LOCAL_KEYS`.
    """
    count = 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if rel.parts[0] in exclude or path.is_symlink() or not path.is_file():
            continue
        trimmed = _config_without_local_keys(path) if arcname == "profile" and rel.as_posix() == "config.json" else None
        if trimmed is None:
            tar.add(path, arcname=f"{arcname}/{rel.as_posix()}", recursive=False)
        else:
            info = tar.gettarinfo(path, arcname=f"{arcname}/{rel.as_posix()}")
            info.size = len(trimmed)
            tar.addfile(info, io.BytesIO(trimmed))
        count += 1
    return count


def _is_within(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #
@common._locked("export")
def _export_core(
    path: Path | str | None = None,
    *,
    profile_dir: Path | None = None,
    jobs_dir: Path | None = None,
) -> dict:
    """Pack `profile_dir` and `jobs_dir` into one `.tar.gz`. Never prints.

    Runs under the ledger lock, so the archive never catches a run halfway.

    Args:
        path: The archive to write, or a directory to write
            ``door-export-<date>.tar.gz`` into. Default: the current directory.

    Returns:
        ``{"path", "files", "bytes"}``.

    Raises:
        FileNotFoundError: there is no `profile_dir/config.json` to export.
        FileExistsError: the archive already exists.
        ValueError: the archive would land inside `profile_dir` or `jobs_dir`.
    """
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR

    if not (profile_dir / "config.json").is_file():
        raise FileNotFoundError(f"nothing to export: {profile_dir / 'config.json'} not found")

    target = Path(path).expanduser() if path else Path.cwd()
    if target.is_dir():
        target = target / _default_name()
    if _is_within(target.parent, profile_dir) or _is_within(target.parent, jobs_dir):
        raise ValueError(f"write the export outside {profile_dir} and {jobs_dir}, not to {target}")
    if target.exists():
        raise FileExistsError(f"{target} already exists — pass another path")

    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.dumps({"format": FORMAT, "exported_at": datetime.now(timezone.utc).isoformat()}).encode()
    tmp = target.with_name(target.name + ".tmp")
    try:
        with tarfile.open(tmp, "w:gz") as tar:
            info = tarfile.TarInfo(_MANIFEST)
            info.size = len(manifest)
            info.mtime = int(datetime.now().timestamp())
            tar.addfile(info, io.BytesIO(manifest))
            files = _add_tree(tar, profile_dir, "profile", _EXCLUDED["profile"])
            if jobs_dir.is_dir():
                files += _add_tree(tar, jobs_dir, "jobs", _EXCLUDED["jobs"])
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    return {"path": str(target), "files": files, "bytes": target.stat().st_size}


# --------------------------------------------------------------------------- #
# import
# --------------------------------------------------------------------------- #
def _read_manifest(tar: tarfile.TarFile, archive: Path) -> dict:
    not_ours = f"{archive} is not an export from The other door"
    try:
        member = tar.getmember(_MANIFEST)
        manifest = json.load(tar.extractfile(member))
    except (KeyError, AttributeError, TypeError, ValueError):
        raise ValueError(f"{not_ours} (no readable {_MANIFEST})") from None
    if not isinstance(manifest, dict) or not isinstance(manifest.get("format"), int):
        raise ValueError(f"{not_ours} ({_MANIFEST} has no format)")
    if manifest["format"] > FORMAT:
        raise ValueError(
            f"{archive} was written by a newer version of The other door (format {manifest['format']}); update it first"
        )
    return manifest


def _read_versions(tar: tarfile.TarFile) -> dict:
    """The data versions the archive carries: ``{"profile", "jobs"}``, None for a folder with no `.data_version`.

    Raises:
        migrations.RefusedData: a version member that is not `<major>.<n>` (never read as 0.0).
    """
    versions: dict = {}
    for folder in ("profile", "jobs"):
        versions[folder] = None
        try:
            member = tar.getmember(f"{folder}/{migrations.VERSION_FILE}")
        except KeyError:
            continue
        handle = tar.extractfile(member) if member.isfile() else None
        text = handle.read(64).decode("utf-8", "replace").strip() if handle else ""
        try:
            versions[folder] = migrations.Version.parse(text)
        except ValueError:
            raise migrations.RefusedData("newer", versions, migrations.ARCHIVE_NEWER) from None
    return versions


def _members_to_extract(tar: tarfile.TarFile, archive: Path) -> list[tarfile.TarInfo]:
    """Every file/dir under profile/ or jobs/, minus lock files.

    Raises ValueError on anything else — an absolute path, `..`, a link, a
    device, an entry outside profile/ and jobs/ — so nothing is extracted.
    """
    members = []
    has_config = False
    for member in tar.getmembers():
        if member.name == _MANIFEST:
            continue
        parts = PurePosixPath(member.name).parts
        if (
            member.name.startswith("/")
            or ".." in parts
            or not parts
            or parts[0] not in _EXCLUDED
            or not (member.isfile() or member.isdir())
        ):
            raise ValueError(f"{archive}: unexpected entry {member.name!r}; nothing was imported")
        if len(parts) > 1 and parts[1] in _EXCLUDED[parts[0]]:
            continue
        if member.isfile() and parts == ("profile", "config.json"):
            has_config = True
        members.append(member)
    if not has_config:
        raise ValueError(f"{archive} has no profile/config.json; nothing was imported")
    return members


def _new_backup_dir(backups_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate, n = backups_dir / stamp, 1
    while candidate.exists():
        n += 1
        candidate = backups_dir / f"{stamp}-{n}"
    candidate.mkdir(parents=True)
    return candidate


def _swap_in(staging: Path, profile_dir: Path, jobs_dir: Path, backup: Path | None) -> list[str]:
    """Move the current data into `backup` and the staged data into place.

    `jobs_dir` itself stays — only its contents move — because it holds the
    open lock file, and Windows cannot rename a folder with an open file in
    it.
    """
    if profile_dir.exists():
        shutil.move(profile_dir, backup / "profile")
    shutil.move(staging / "profile", profile_dir)

    old_jobs = [c for c in jobs_dir.iterdir() if c.name not in _LOCK_FILES]
    if old_jobs:
        (backup / "jobs").mkdir()
        for child in old_jobs:
            shutil.move(child, backup / "jobs" / child.name)
    staged_jobs = staging / "jobs"
    if staged_jobs.is_dir():
        for child in staged_jobs.iterdir():
            shutil.move(child, jobs_dir / child.name)


def _path_warnings(config_path: Path) -> list[str]:
    """Config paths that point somewhere this computer doesn't have."""
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"{config_path} is not valid JSON; run `doctor`"]
    warnings = []
    for key in _PATH_KEYS:
        value = config.get(key)
        if not isinstance(value, str):
            continue
        p = Path(value).expanduser()
        if p.is_absolute() and not p.exists():
            warnings.append(f"{key} points to {value}, which doesn't exist on this computer; update profile/config.json")
    return warnings


@common._locked("import")
def _import_core(
    archive: Path | str,
    *,
    profile_dir: Path | None = None,
    jobs_dir: Path | None = None,
    backups_dir: Path | None = None,
) -> dict:
    """Replace `profile_dir` and `jobs_dir` with an archive from `_export_core`. Never prints.

    The archive is checked in full before anything moves (an archive from a newer version of The other door, or of an older major, is
    refused); the data it replaces goes to ``backups_dir/<timestamp>/``. An older archive is upgraded right after
    (`migrations.upgrade_all`; a failed step is one warning, the data stays as imported).

    Returns:
        ``{"archive", "files", "profile_dir", "jobs_dir", "backup_dir",
        "warnings", "data_versions"}`` — ``backup_dir`` is None when there was
        nothing to back up; ``warnings`` lists config paths this computer
        doesn't have and a failed upgrade; ``data_versions`` is what the archive carried.

    Raises:
        FileNotFoundError: the archive doesn't exist.
        ValueError: it isn't an export from The other door, or holds an entry outside profile/ and jobs/.
        migrations.RefusedData (a ValueError): its data version is above this build's, of an older major, or unreadable.
    """
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR
    if backups_dir is None:
        backups_dir = workspace.BACKUPS_DIR

    archive = Path(archive).expanduser()
    if not archive.is_file():
        raise FileNotFoundError(f"{archive} not found")
    try:
        tar = tarfile.open(archive, "r:*")
    except tarfile.TarError:
        raise ValueError(f"{archive} is not an export from The other door (not a .tar.gz archive)") from None

    with tar:
        _read_manifest(tar, archive)
        members = _members_to_extract(tar, archive)
        versions = _read_versions(tar)
        migrations.refuse(versions)
        profile_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".door-import-", dir=profile_dir.parent))
        try:
            tar.extractall(staging, members=members, filter="data")
            _keep_local_keys(staging / "profile" / "config.json", profile_dir / "config.json")
            jobs_dir.mkdir(parents=True, exist_ok=True)
            if all(c.name in _LOCK_FILES or c.name == migrations.VERSION_FILE for c in jobs_dir.iterdir()):
                (jobs_dir / migrations.VERSION_FILE).unlink(missing_ok=True)  # only the stamp of an empty folder
            has_old_jobs = any(c.name not in _LOCK_FILES for c in jobs_dir.iterdir())
            backup = _new_backup_dir(backups_dir) if profile_dir.exists() or has_old_jobs else None
            _swap_in(staging, profile_dir, jobs_dir, backup)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    migrations.ensure_folder(jobs_dir, "jobs")  # an archive with no jobs: the folder is new, so stamped
    warnings = _path_warnings(profile_dir / "config.json")
    upgrade = migrations.upgrade_all(profile_dir, jobs_dir, backups_dir)
    if upgrade:
        warnings.append(upgrade["message"])

    return {
        "archive": str(archive),
        "files": sum(1 for m in members if m.isfile()),
        "profile_dir": str(profile_dir),
        "jobs_dir": str(jobs_dir),
        "backup_dir": str(backup) if backup else None,
        "warnings": warnings,
        "data_versions": {k: str(v) if v else None for k, v in versions.items()},
    }


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
        result = _export_core(path, profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR)
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
        result = _import_core(archive, profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR)
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


@common._locked("sync")
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


@click.command("disconnect")
def disconnect():
    """Forget this computer's Google Drive connection (the archive on Drive stays)."""
    result = _disconnect_core()
    common._mark_line(
        common._console(), "ok",
        "Disconnected from Google Drive" if result["disconnected"] else "Not connected to Google Drive",
    )
