"""Upgrading a user's data between releases (#56).

Each of `profile/` and `jobs/` has its own data version, a plain integer in `<folder>/.data_version`
(a file of its own: `config.json` is edited by hand and validated strictly). A folder's current version is the
number of steps it has; a release adds a step only when the data it writes differs from the last release's
(the `data-migrator` agent writes it, at release time). v0.1.0's data has no file: version 0.

A step is a function of the folder that moves it from version N to N+1. Every step is idempotent: a missing file
is no proof of old data (a folder made on the fly, or by a build from `main`, has none), so a step run on data
already in the new shape changes nothing. Steps are never deleted: a user who skips releases gets every one in turn.

`upgrade_all` runs at the start of the MCP server and the CLI, under the `jobs/` ledger lock (read after taking it, so
a second process finds the work done): the folder is copied to `backups/upgrade-<folder>-<from>-<to>-<time>/`, the
steps run, the version is written after the last. A failing step restores the folder from the backup and leaves the
version; newer data (version above ours) is never written to. Either leaves a `status()` the tools answer with.
`upgrade_folder`/`read_version` stand alone for import and Drive (PR 2).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from door.core import lock as lock_mod
from door.core import problem_log, workspace

VERSION_FILE = ".data_version"
BACKUP_PREFIX = "upgrade-"
KEEP_BACKUPS = 2
_LOCK_WAIT_S = 3.0  # how long a start waits for a run (or another start) holding the lock
_LOCK_FILES = (".lock", ".lock.json", ".progress.json")

FAILED = "Your data could not be upgraded to this version: {step}. Nothing was changed. Send a report from Settings."
NEWER = "This data was written by a newer version of The other door. Install the latest version."


class DataVersionError(ValueError):
    """A `.data_version` that is not a non-negative integer."""


@dataclass(frozen=True)
class Step:
    """One move of a folder from version N to N+1; *run* takes the folder and changes nothing outside it."""

    name: str
    run: Callable[[Path], None]


# --------------------------------------------------------------------------- #
# The steps
# --------------------------------------------------------------------------- #

# SHA-256 of the files v0.1.0's `init` copied into `profile/` (`profile.example/` has not changed since).
_SHIPPED_TEMPLATES = {
    "cv.template.tex": "a9abadba23e80da8c1b13558bfaf7a362d466c0d3af2b9b1bb59030a518d5fc8",
    "cover-letter.template.tex": "b88e5a3b4c1442a50a94f477de0eca88021532cd317a8a3746d480517768a129",
}
_SHIPPED_FONTS = {
    "Figtree-Italic.otf": "cdfa060d97e57fe4724753dedaa3237190471117cc2fa5e40450830f89347890",
    "Figtree-OFL.txt": "140d37233e7f3ce7313798befa9600893bcceaf41a55fa0fa5ad52f7f657a268",
    "Figtree-Regular.otf": "bb78b465694e43b0620682e4bc3ecdc4d930f2fe3b3dd88c32783603fc55c3c6",
    "Figtree-SemiBold.otf": "a93cca2b8fca486b51058305a77cbf91fe49a0471df35af44f5c26604896f162",
    "Figtree-SemiBoldItalic.otf": "65f6dc3a9aeea0edcfe48a4d791db5301ad22c2b54c6abdf296a9f1c4e9dd327",
    "YoungSerif-Bold.otf": "0df223774823d09e8bfb3ed1bfa2718d1c36aebe3ffce8076f9b206f9aec7a5b",
    "YoungSerif-OFL.txt": "737d8d343b674c6894f373de71a044b6782c130f2aebf180933d63ddf7a3dc19",
}
# The config keys that named those copies, with the value `init` wrote.
_TEMPLATE_KEYS = {
    "cv_template": ("cv.template.tex", "profile/cv.template.tex"),
    "cover_letter_template": ("cover-letter.template.tex", "profile/cover-letter.template.tex"),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _remove_if_shipped(path: Path, digest: str) -> None:
    if path.is_file() and _sha256(path) == digest:
        path.unlink()


def _templates_from_code(profile_dir: Path) -> None:
    """0 -> 1: the templates and fonts come from the code, not from a copy in `profile/`.

    Removes the copies that are byte for byte a shipped version (an edited one is the user's own and stays), the
    `fonts/` folder once empty, and the config keys that named a removed copy.
    """
    profile_dir = Path(profile_dir)
    if not profile_dir.is_dir():
        return
    for name, digest in _SHIPPED_TEMPLATES.items():
        _remove_if_shipped(profile_dir / name, digest)
    fonts = profile_dir / "fonts"
    if fonts.is_dir():
        for name, digest in _SHIPPED_FONTS.items():
            _remove_if_shipped(fonts / name, digest)
        if not any(fonts.iterdir()):
            fonts.rmdir()
    config_path = profile_dir / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(config, dict):
        return
    dropped = [
        key for key, (name, default) in _TEMPLATE_KEYS.items()
        if config.get(key) == default and not (profile_dir / name).exists()
    ]
    if dropped:
        for key in dropped:
            del config[key]
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")


PROFILE_STEPS: list[Step] = [Step("templates come from the code", _templates_from_code)]
JOBS_STEPS: list[Step] = []


def current(folder: str) -> int:
    """The version of ``"profile"`` or ``"jobs"`` this build writes."""
    return len({"profile": PROFILE_STEPS, "jobs": JOBS_STEPS}[folder])


# --------------------------------------------------------------------------- #
# Versions
# --------------------------------------------------------------------------- #
def read_version(folder: Path) -> int | None:
    """The folder's data version, None when it has no `.data_version` (v0.1.0's data, or a folder made on the fly).

    Raises:
        DataVersionError: the file is there but is not a non-negative integer (never read as 0).
    """
    try:
        text = (Path(folder) / VERSION_FILE).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise DataVersionError(f"cannot read {Path(folder) / VERSION_FILE} ({exc})") from None
    text = text.strip()
    if not text.isascii() or not text.isdigit():
        raise DataVersionError(f"{Path(folder) / VERSION_FILE} holds {text!r}, not a version number")
    return int(text)


def write_version(folder: Path, version: int) -> None:
    Path(folder).mkdir(parents=True, exist_ok=True)
    path = Path(folder) / VERSION_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(f"{version}\n", encoding="utf-8")
    tmp.replace(path)


def stamp_new(folder: Path, name: str = "profile") -> None:
    """Mark a folder just created by this build (``name``: "profile" or "jobs") as at its current version."""
    folder = Path(folder)
    if read_version(folder) is None:
        write_version(folder, current(name))


# --------------------------------------------------------------------------- #
# Backup and restore
# --------------------------------------------------------------------------- #
def _skip_locks(root: Path):
    """`copytree`'s ignore: the lock files at the top of *root* (held by this very process) are not data."""
    return lambda directory, names: [n for n in names if Path(directory) == root and n in _LOCK_FILES]


def _backup(folder: Path, backups_dir: Path, label: str, source: int, target: int) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backups_dir / f"{BACKUP_PREFIX}{label}-{source}-{target}-{stamp}"
    n = 1
    while dest.exists():
        n += 1
        dest = backups_dir / f"{BACKUP_PREFIX}{label}-{source}-{target}-{stamp}-{n}"
    backups_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(folder, dest, ignore=_skip_locks(Path(folder)), symlinks=True)
    return dest


def _restore(folder: Path, backup: Path) -> None:
    for child in list(Path(folder).iterdir()):
        if child.name in _LOCK_FILES:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in backup.iterdir():
        dest = Path(folder) / child.name
        if child.is_dir():
            shutil.copytree(child, dest, symlinks=True)
        else:
            shutil.copy2(child, dest)


def _prune(backups_dir: Path) -> None:
    """Keep the newest `KEEP_BACKUPS` upgrade backups; an import's backup is never touched."""
    found = sorted(
        (p for p in Path(backups_dir).glob(f"{BACKUP_PREFIX}*") if p.is_dir()),
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    for old in found[KEEP_BACKUPS:]:
        shutil.rmtree(old, ignore_errors=True)


# --------------------------------------------------------------------------- #
# The runner
# --------------------------------------------------------------------------- #
class _StepFailed(Exception):
    def __init__(self, step: str, cause: BaseException):
        super().__init__(step)
        self.step = step
        self.cause = cause


def upgrade_folder(folder: Path, steps: list[Step], *, backups_dir: Path, label: str) -> bool:
    """Bring *folder* to ``len(steps)``: back it up, run the missing steps in order, write the version.

    The caller holds the lock and has checked the version is not newer. Returns whether a step ran.

    Raises:
        _StepFailed: a step raised; the folder was restored from the backup and the version left as it was.
    """
    folder = Path(folder)
    have = read_version(folder) or 0
    want = len(steps)
    if have >= want:
        return False
    backup = _backup(folder, Path(backups_dir), label, have, want)
    ran = ""
    try:
        for step in steps[have:]:
            ran = step.name
            step.run(folder)
        ran = f"writing {VERSION_FILE}"
        write_version(folder, want)
    except BaseException as exc:
        try:
            _restore(folder, backup)
        except Exception as restore_exc:  # noqa: BLE001 - say both
            problem_log.failure("upgrade", f"restore of {label} failed: {restore_exc}")
        raise _StepFailed(ran, exc) from exc
    _prune(Path(backups_dir))
    return True


# What the last `upgrade_all` found: None, or {"state": "failed"|"newer"|"busy", "message": str}.
_state: dict | None = None


def status() -> dict | None:
    """None when the data is upgraded (or nothing to do); else the state tools answer with."""
    return dict(_state) if _state else None


def _set(state: dict | None) -> dict | None:
    global _state
    _state = state
    return status()


def _failed(step: str) -> dict:
    return {"state": "failed", "message": FAILED.format(step=step)}


def _classify(folders, steps_of) -> dict | None:
    """Read each folder's version without the lock: a refusal (newer, garbled) or None."""
    for name, folder in folders:
        if not folder.is_dir():
            continue
        try:
            version = read_version(folder)
        except DataVersionError as exc:
            problem_log.failure("upgrade", str(exc))
            return _failed(f"reading {name}/{VERSION_FILE}")
        if version is not None and version > len(steps_of[name]):
            return {"state": "newer", "message": NEWER}
    return None


def _behind(folders, steps_of) -> bool:
    return any(
        folder.is_dir() and (read_version(folder) or 0) < len(steps_of[name]) for name, folder in folders
    )


def upgrade_all(
    profile_dir: Path | None = None,
    jobs_dir: Path | None = None,
    backups_dir: Path | None = None,
    *,
    profile_steps: list[Step] | None = None,
    jobs_steps: list[Step] | None = None,
) -> dict | None:
    """Upgrade `profile/` then `jobs/` to this build's versions; returns `status()`.

    A folder that does not exist is left alone. Newer or garbled data is refused and nothing is written. Called again
    it is cheap when the data is current (two small file reads), and retries a "busy" state.
    """
    profile_dir = Path(profile_dir if profile_dir is not None else workspace.PROFILE_DIR)
    jobs_dir = Path(jobs_dir if jobs_dir is not None else workspace.JOBS_DIR)
    backups_dir = Path(backups_dir if backups_dir is not None else workspace.BACKUPS_DIR)
    steps_of = {
        "profile": PROFILE_STEPS if profile_steps is None else profile_steps,
        "jobs": JOBS_STEPS if jobs_steps is None else jobs_steps,
    }
    folders = (("profile", profile_dir), ("jobs", jobs_dir))

    refusal = _classify(folders, steps_of)
    if refusal:
        _log_once(refusal)
        return _set(refusal)
    if not _behind(folders, steps_of):
        return _set(None)

    deadline = time.monotonic() + _LOCK_WAIT_S
    while True:
        try:
            with lock_mod.ledger_lock(jobs_dir, "upgrade"):
                return _set(_upgrade_locked(folders, steps_of, backups_dir))
        except lock_mod.LockHeldError as exc:
            if time.monotonic() >= deadline:
                busy = {"state": "busy", "message": str(exc)}
                return _set(busy)
            time.sleep(0.2)


def _upgrade_locked(folders, steps_of, backups_dir: Path) -> dict | None:
    refusal = _classify(folders, steps_of)  # read again, now the lock is ours: another start may have done it
    if refusal:
        _log_once(refusal)
        return refusal
    for name, folder in folders:
        if not folder.is_dir():
            continue
        try:
            upgrade_folder(folder, steps_of[name], backups_dir=backups_dir, label=name)
        except _StepFailed as exc:
            problem_log.failure("upgrade", f"{name} step {exc.step!r} failed: {exc.cause}")
            return _failed(exc.step)
    return None


_logged: set[str] = set()


def _log_once(state: dict) -> None:
    if state["message"] not in _logged:
        _logged.add(state["message"])
        problem_log.failure("upgrade", state["message"])
