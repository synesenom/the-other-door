"""Packing profile/ and jobs/ into one archive and unpacking one (`export` and `import`; also Google Drive's, `core/sync/sync.py`).

The archive is a `.tar.gz` holding `manifest.json`, `profile/...` and `jobs/...`.
The ledger lock never goes in it.
`_import_core` replaces the local data, after moving it to `backups/<timestamp>/`. The cores never print; the commands
that render them are in `commands/archive.py`.
"""

import io
import json
import shutil
import tarfile
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath

from door.core import lock, migrations, usage, utils, workspace

# Bump when the archive layout changes; `import` refuses a newer format.
FORMAT = 1

_MANIFEST = "manifest.json"
# Never exported, kept in place on import: the lock files, and this computer's Claude usage log (#575).
_LOCK_FILES = (".lock", ".lock.json", ".progress.json", usage.LOG_NAME)
_EXCLUDED = {"profile": (migrations.MARKER,), "jobs": (*_LOCK_FILES, migrations.MARKER)}

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
@lock.locked("export")
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

    manifest = json.dumps({"format": FORMAT, "exported_at": datetime.now(timezone.utc).isoformat()}).encode()
    # mode 0o600: the export holds the whole profile, so it stays private to the user
    with utils.atomic_target(target, mode=0o600) as tmp:
        with tarfile.open(tmp, "w:gz") as tar:
            info = tarfile.TarInfo(_MANIFEST)
            info.size = len(manifest)
            info.mtime = int(datetime.now().timestamp())
            tar.addfile(info, io.BytesIO(manifest))
            files = _add_tree(tar, profile_dir, "profile", _EXCLUDED["profile"])
            if jobs_dir.is_dir():
                files += _add_tree(tar, jobs_dir, "jobs", _EXCLUDED["jobs"])

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
        if backup is None:  # only the version stamp of a first start: nothing to keep
            shutil.rmtree(profile_dir)
        else:
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


@lock.locked("import")
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
        with utils.staging(profile_dir.parent, ".door-import-") as staging:
            tar.extractall(staging, members=members, filter="data")
            _keep_local_keys(staging / "profile" / "config.json", profile_dir / "config.json")
            jobs_dir.mkdir(parents=True, exist_ok=True)
            if all(c.name in _LOCK_FILES or c.name == migrations.VERSION_FILE for c in jobs_dir.iterdir()):
                (jobs_dir / migrations.VERSION_FILE).unlink(missing_ok=True)  # only the stamp of an empty folder
            has_old_jobs = any(c.name not in _LOCK_FILES for c in jobs_dir.iterdir())
            has_old_profile = profile_dir.exists() and any(
                c.name != migrations.VERSION_FILE for c in profile_dir.iterdir()
            )
            backup = _new_backup_dir(backups_dir) if has_old_profile or has_old_jobs else None
            _swap_in(staging, profile_dir, jobs_dir, backup)

    migrations.ensure_folder(jobs_dir, "jobs")  # an archive with no jobs: the folder is new, so stamped
    warnings: list[str] = []
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
