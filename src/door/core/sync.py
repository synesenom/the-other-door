"""Google Drive sync of profile/ and jobs/ (issue #265).

A pull refuses an archive from a newer version of The other door (#56) and upgrades an older one; a computer that
refused does not push until it has been upgraded and pulled. `decide` is the pure table; `fingerprint` tells whether local data changed
since the last pull; `pull`/`push`/`sync_now` move the archive; `on_acquire`
and `on_release` are the ledger lock's hooks. Cores never print; they `report()`.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from door.core import drive, migrations, usage, workspace
from door.core.lock import SyncConflict
from door.core.progress import report

__all__ = ["SyncConflict", "decide", "fingerprint", "pull", "push", "sync_now", "on_acquire", "on_release", "drain_notes"]

_IGNORED = {".lock", ".lock.json", ".progress.json", usage.LOG_NAME}  # usage.jsonl: this computer's, written outside the lock


def decide(remote_version, synced_version, dirty: bool, *, has_local_data: bool = True) -> str:
    """What to do: ``"nothing"``, ``"push"``, ``"pull"`` or ``"conflict"``.

    Args:
        remote_version: The archive's version on Drive, None when absent.
        synced_version: The version this computer last pulled or pushed, None if never.
        dirty: Local data changed since that sync.
        has_local_data: There is local data worth keeping (a profile/config.json).
    """
    if remote_version is None:
        return "push" if has_local_data else "nothing"
    if synced_version is None:
        return "conflict" if has_local_data else "pull"
    if remote_version == synced_version:
        return "push" if dirty else "nothing"
    return "conflict" if dirty else "pull"


def fingerprint(profile_dir: Path, jobs_dir: Path) -> str:
    """A hash of (relative path, size, mtime) of every file in profile/ and jobs/, minus lock files."""
    digest = hashlib.sha256()
    for label, root in (("profile", Path(profile_dir)), ("jobs", Path(jobs_dir))):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            if not path.is_file() or path.is_symlink():
                continue
            if len(rel.parts) == 1 and rel.name in _IGNORED:
                continue
            st = path.stat()
            digest.update(f"{label}/{rel.as_posix()}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return digest.hexdigest()


# --------------------------------------------------------------------------- pull / push
def _dirs(profile_dir, jobs_dir, backups_dir=None):
    return (
        Path(profile_dir) if profile_dir is not None else workspace.PROFILE_DIR,
        Path(jobs_dir) if jobs_dir is not None else workspace.JOBS_DIR,
        Path(backups_dir) if backups_dir is not None else workspace.BACKUPS_DIR,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_local_data(profile_dir: Path) -> bool:
    return (profile_dir / "config.json").is_file()


NEWER_ON_DRIVE = "Google Drive has data from a newer version of The other door; install it on this computer too"


def _local_versions(profile_dir: Path, jobs_dir: Path) -> dict:
    versions = {}
    for name, folder in (("profile", profile_dir), ("jobs", jobs_dir)):
        try:
            versions[name] = migrations.read_version(folder)
        except migrations.DataVersionError:
            versions[name] = None
    return versions


def _check_push_allowed(profile_dir: Path, jobs_dir: Path) -> dict:
    """Never replace Drive's archive from a computer that has not been upgraded to it: returns the local versions.

    Raises:
        DriveError: a pull refused a newer archive and none has been taken since, or this computer's versions are
            below the ones the archive on Drive was last known to carry.
    """
    state = drive.read_state() or {}
    local = _local_versions(profile_dir, jobs_dir)
    known = state.get("data_versions") or {}
    behind = any((local.get(f) or 0) < (known.get(f) or 0) for f in ("profile", "jobs"))
    if state.get("refused_newer") or behind:
        raise drive.DriveError(NEWER_ON_DRIVE)
    return local


def push(*, profile_dir=None, jobs_dir=None) -> dict:
    """Export profile/ and jobs/ and upload the archive; record the version and fingerprint.

    Returns ``{"action": "push", "version"}``, or ``{"action": "skipped"}`` when
    there is no profile/config.json to export yet.
    """
    from door.commands import archive as archive_cmd

    profile_dir, jobs_dir, _ = _dirs(profile_dir, jobs_dir)
    if not _has_local_data(profile_dir):
        return {"action": "skipped"}
    local = _check_push_allowed(profile_dir, jobs_dir)
    with tempfile.TemporaryDirectory(prefix="door-sync-") as tmp:
        target = Path(tmp) / drive.FILE_NAME
        archive_cmd._export_core(target, profile_dir=profile_dir, jobs_dir=jobs_dir)
        version = drive.upload(target)
    drive.update_state(
        synced_version=version,
        fingerprint=fingerprint(profile_dir, jobs_dir),
        last_synced=_now(),
        last_error=None,
        data_versions=local,
        refused_newer=False,
    )
    return {"action": "push", "version": version}


def pull(*, profile_dir=None, jobs_dir=None, backups_dir=None) -> dict:
    """Download the archive and replace the local data with it (the old data goes to backups/).

    Only the backup the previous sync pull made is deleted; backups from a manual
    `data import` stay.
    """
    from door.commands import archive as archive_cmd

    profile_dir, jobs_dir, backups_dir = _dirs(profile_dir, jobs_dir, backups_dir)
    meta = drive.remote_meta()
    if meta is None:
        raise drive.DriveError("There is no archive of The other door on Google Drive.")
    with tempfile.TemporaryDirectory(prefix="door-sync-") as tmp:
        target = Path(tmp) / drive.FILE_NAME
        drive.download(target)
        try:
            result = archive_cmd._import_core(target, profile_dir=profile_dir, jobs_dir=jobs_dir, backups_dir=backups_dir)
        except migrations.NewerData as exc:
            drive.update_state(refused_newer=True, data_versions=exc.versions, last_error=NEWER_ON_DRIVE)
            raise
    state = drive.read_state() or {}
    for old in state.get("sync_backups", []):
        shutil.rmtree(old, ignore_errors=True)
    drive.update_state(
        synced_version=meta["version"],
        fingerprint=fingerprint(profile_dir, jobs_dir),
        last_synced=_now(),
        last_error=None,
        data_versions=result["data_versions"],
        refused_newer=False,
        sync_backups=[result["backup_dir"]] if result["backup_dir"] else None,
    )
    return {"action": "pull", "version": meta["version"], "files": result["files"], "warnings": result["warnings"]}


def _conflict_message() -> str:
    return (
        "Google Drive and this computer both changed since they last synced; nothing was overwritten. "
        "Run `./door data sync --keep-local` to replace Drive with this computer's data, or "
        "`./door data sync --keep-drive` to replace this computer's data with Drive's "
        "(the replaced data is kept in backups/ for a pull)."
    )


def _state_or_raise() -> dict:
    state = drive.read_state()
    if not state or not state.get("refresh_token"):
        raise drive.DriveError("Google Drive is not connected; run `./door data connect`.")
    return state


def _decide(state: dict, meta, profile_dir: Path, jobs_dir: Path) -> str:
    has_local = _has_local_data(profile_dir)
    saved = state.get("fingerprint")
    dirty = has_local and saved != fingerprint(profile_dir, jobs_dir)
    return decide(meta["version"] if meta else None, state.get("synced_version"), dirty, has_local_data=has_local)


def sync_now(*, keep_local: bool = False, keep_drive: bool = False, profile_dir=None, jobs_dir=None, backups_dir=None) -> dict:
    """Bring this computer and Drive level: decide, then pull or push.

    Raises:
        SyncConflict: both sides changed and neither `keep_local` nor `keep_drive` was given.
        DriveError: not connected, offline, revoked, ...
    """
    profile_dir, jobs_dir, backups_dir = _dirs(profile_dir, jobs_dir, backups_dir)
    state = _state_or_raise()
    try:
        return _sync_now(state, keep_local, keep_drive, profile_dir, jobs_dir, backups_dir)
    except drive.DriveError as exc:
        # Kept like a lock hook's failure, so the Drive row says the last sync failed; a success clears it.
        drive.update_state(last_error=str(exc))
        raise


def _sync_now(state: dict, keep_local: bool, keep_drive: bool, profile_dir: Path, jobs_dir: Path, backups_dir: Path) -> dict:
    meta = drive.remote_meta()
    if keep_local:
        action = "push"
    elif keep_drive:
        if meta is None:
            raise drive.DriveError("There is nothing on Google Drive to keep.")
        action = "pull"
    else:
        action = _decide(state, meta, profile_dir, jobs_dir)
    if action == "conflict":
        raise SyncConflict(_conflict_message())
    if action == "push":
        return push(profile_dir=profile_dir, jobs_dir=jobs_dir)
    if action == "pull":
        return pull(profile_dir=profile_dir, jobs_dir=jobs_dir, backups_dir=backups_dir)
    return {"action": "nothing"}


# --------------------------------------------------------------------------- lock hooks
# Lock blocks whose acquire already failed to sync: their release stays quiet (one warning).
_failed: set[str] = set()


def _applies(jobs_dir: Path) -> bool:
    """Sync only the real workspace's jobs/, and only on a connected computer."""
    try:
        if Path(jobs_dir).resolve() != Path(workspace.JOBS_DIR).resolve():
            return False
    except OSError:
        return False
    return drive.read_state() is not None


# What the lock hooks did, for the CLI to say once its command is done (`drain_notes`):
# ``(kind, message)``, kind ``pulled``, ``pushed`` or ``warning``. Bounded, since the MCP
# server never drains it.
_notes: deque = deque(maxlen=10)


def _note(kind: str, message: str) -> None:
    _notes.append((kind, message))


def drain_notes() -> list[tuple[str, str]]:
    """The notes since the last drain, oldest first, and forget them."""
    notes = list(_notes)
    _notes.clear()
    return notes


def _warn(exc: Exception) -> None:
    drive.update_state(last_error=str(exc))
    message = "Drive sync skipped (offline)" if isinstance(exc, drive.DriveOffline) else f"Drive sync skipped: {exc}"
    report(message)
    _note("warning", message)


def on_acquire(purpose: str, jobs_dir: Path) -> None:
    """Before a ledger-writing block: pull what another computer pushed.

    Raises `SyncConflict` when both sides changed; any other failure is one warning.
    """
    if not _applies(jobs_dir):
        return
    key = str(Path(jobs_dir).resolve())
    _failed.discard(key)
    profile_dir, jobs_dir, backups_dir = _dirs(None, jobs_dir)
    try:
        state = _state_or_raise()
        action = _decide(state, drive.remote_meta(), profile_dir, jobs_dir)
        if action == "conflict":
            raise SyncConflict(_conflict_message())
        if action == "pull":
            report("Pulling newer data from Google Drive")
            pull(profile_dir=profile_dir, jobs_dir=jobs_dir, backups_dir=backups_dir)
            _note("pulled", "Pulled newer data from Google Drive (this computer's previous data is in backups/)")
    except SyncConflict:
        raise
    except migrations.NewerData:
        _failed.add(key)  # pull recorded the refusal; the release stays quiet and pushes nothing
        report(NEWER_ON_DRIVE)
        _note("warning", NEWER_ON_DRIVE)
    except Exception as exc:  # noqa: BLE001 - sync must never fail a command
        _failed.add(key)
        _warn(exc)


def on_release(purpose: str, jobs_dir: Path) -> None:
    """After a ledger-writing block: push when the data changed since the last sync."""
    if not _applies(jobs_dir):
        return
    key = str(Path(jobs_dir).resolve())
    if key in _failed:
        _failed.discard(key)
        return
    profile_dir, jobs_dir, _ = _dirs(None, jobs_dir)
    try:
        state = _state_or_raise()
        if not _has_local_data(profile_dir) or state.get("fingerprint") == fingerprint(profile_dir, jobs_dir):
            return
        action = _decide(state, drive.remote_meta(), profile_dir, jobs_dir)
        if action == "push":
            report("Pushing changes to Google Drive")
            push(profile_dir=profile_dir, jobs_dir=jobs_dir)
            _note("pushed", "Synced to Google Drive")
        elif action in ("conflict", "pull"):
            raise drive.DriveError("Google Drive changed meanwhile; run `./door data sync`")
    except Exception as exc:  # noqa: BLE001 - sync must never fail a command
        _warn(exc)
