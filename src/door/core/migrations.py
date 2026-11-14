"""Upgrading a user's data between releases (#56).

Each of `profile/` and `jobs/` has its own data version in `<folder>/.data_version` (a file of its own: `config.json`
is edited by hand and validated strictly), written `<major>.<n>`, e.g. `0.1`. `<major>` is the app's major version
(`door.version.VERSION`, read at call time); `<n>` is the number of steps applied within that major, so a folder's
current version is `<app major>.<number of steps>`. A release adds a step only when the data it writes differs from
the last release's (the `data-migrator` agent writes it, at release time). v0.1.0 wrote no file: a folder with data
and no file is `0.0`. Anything else in the file is garbled (`DataVersionError`), never read as 0.

Across a major version nothing is upgraded: data of an older major is refused ("old_major"), data of a later major
or of more steps than this build has is refused ("newer"). A release that bumps the major empties `PROFILE_STEPS` and
`JOBS_STEPS` (the steps of the old major are dropped with it) and writes no step for the bump.

The file is authoritative: a folder this build creates is stamped with the current version at once (`ensure_folder`,
called where a folder is made: `ledger_lock` for `jobs/`, the writers of `profile/`), so a folder with data and no
file can only be v0.1.0's. A step is a function of the folder that moves it from version N to N+1 and may assume the
data is in the shape of version N. Steps are never deleted within a major: a user who skips releases gets every one
in turn.

`upgrade_all` runs at the start of the MCP server and the CLI, under the `jobs/` ledger lock (read after taking it, so
a second process finds the work done): the folder is copied to `backups/upgrade-<folder>-<from>-<to>-<time>/`, the
steps run, the version is written after the last. A failing step restores the folder from the backup and leaves the
version; refused data (newer, older major) is never written to. Either leaves a `status()` the tools answer with.
An import or a Drive pull refuses such an archive (`refuse`, raising `RefusedData`) before it changes anything and
runs `upgrade_all` right after the swap. Google Drive keeps the two versions on the archive file itself
(`appProperties`), so a pull or push can refuse without downloading (`core/sync.py`).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from door import version as app_version
from door.core import lock as lock_mod
from door.core import problem_log, workspace

VERSION_FILE = ".data_version"
BACKUP_PREFIX = "upgrade-"
KEEP_BACKUPS = 2
_LOCK_WAIT_S = 3.0  # how long a start waits for a run (or another start) holding the lock
_LOCK_FILES = (".lock", ".lock.json", ".progress.json")

FAILED = "Your data could not be upgraded to this version: {step}. Nothing was changed. Send a report from Settings."
NEWER = "This data was written by a newer version of The other door. Install the latest version."
ARCHIVE_NEWER = "This archive was written by a newer version of The other door. Install the latest version."
OLD_MAJOR = "This data was written by The other door {data}.x. Version {app} cannot open it: keep using {data}.x, or start a new profile."


class DataVersionError(ValueError):
    """A `.data_version` that is not `<major>.<n>`."""


@dataclass(frozen=True, order=True)
class Version:
    """A folder's data version: the app's major and the steps applied within it."""

    major: int
    n: int

    @classmethod
    def parse(cls, text: str) -> "Version":
        """Read ``"<major>.<n>"`` strictly; ValueError for anything else."""
        match = re.fullmatch(r"([0-9]+)\.([0-9]+)", text.strip()) if text.isascii() else None
        if not match:
            raise ValueError(f"{text!r} is not a data version")
        return cls(int(match.group(1)), int(match.group(2)))

    def __str__(self) -> str:
        return f"{self.major}.{self.n}"


UNVERSIONED = Version(0, 0)  # a folder with data and no file: v0.1.0's


def app_major() -> int:
    return int(app_version.VERSION.split(".")[0])


def compare(have: Version, want: Version) -> str:
    """``"current"``, ``"upgrade"`` (have is behind within the major), ``"newer"`` or ``"old_major"``."""
    if have.major < want.major:
        return "old_major"
    if have.major > want.major or have.n > want.n:
        return "newer"
    return "upgrade" if have.n < want.n else "current"


def refusal_message(state: str, have: Version, want: Version, *, archive: bool = False) -> str:
    if state == "old_major":
        return OLD_MAJOR.format(data=have.major, app=want.major)
    return ARCHIVE_NEWER if archive else NEWER


class RefusedData(ValueError):
    """An archive (import or Google Drive) this build cannot open: ``state`` is "newer" or "old_major".

    ``versions`` is ``{"profile": Version | None, "jobs": Version | None}`` as the archive named them (None: unknown).
    """

    def __init__(self, state: str, versions: dict, message: str):
        super().__init__(message)
        self.state = state
        self.versions = versions


@dataclass(frozen=True)
class Step:
    """One move of a folder from version N to N+1; *run* takes the folder and changes nothing outside it.

    *changes* are the paths into a release's saved `expected.json` (`tests/data_versions/<X.Y.Z>/`, #57) that the step
    changes on purpose, as globs over the dotted path (``show_profile.config.cv_template``; ``*`` is any text, a list
    item is ``[index]``; a path covers everything under it). The release gate fails on any other difference between
    what the old release read back and what this build reads back from the upgraded data, a dropped value included.
    """

    name: str
    run: Callable[[Path], None]
    changes: tuple[str, ...] = ()


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


PROFILE_STEPS: list[Step] = [
    Step(
        "templates come from the code", _templates_from_code,
        changes=(
            "show_profile.config.cv_template", "show_profile.config.cover_letter_template",  # the keys named the copies
            "show_profile.templates.*.path",  # the template read is the code's, not a copy in profile/
        ),
    ),
]
JOBS_STEPS: list[Step] = []


def current(folder: str) -> Version:
    """The version of ``"profile"`` or ``"jobs"`` this build writes."""
    return Version(app_major(), len({"profile": PROFILE_STEPS, "jobs": JOBS_STEPS}[folder]))


# --------------------------------------------------------------------------- #
# Versions
# --------------------------------------------------------------------------- #
def read_version(folder: Path) -> Version | None:
    """The folder's data version, None when it has no `.data_version` (v0.1.0's data: `UNVERSIONED`).

    Raises:
        DataVersionError: the file is there but is not `<major>.<n>` (never read as 0.0).
    """
    try:
        text = (Path(folder) / VERSION_FILE).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise DataVersionError(f"cannot read {Path(folder) / VERSION_FILE} ({exc})") from None
    try:
        return Version.parse(text)
    except ValueError:
        raise DataVersionError(f"{Path(folder) / VERSION_FILE} holds {text.strip()!r}, not a data version") from None


def refuse(versions: dict) -> None:
    """Raise `RefusedData` when the archive's version of either folder is newer than this build's or of an older major
    (None = unknown: fine)."""
    for folder in ("profile", "jobs"):
        have = versions.get(folder)
        if have is None:
            continue
        want = current(folder)
        state = compare(have, want)
        if state in ("newer", "old_major"):
            raise RefusedData(state, versions, refusal_message(state, have, want, archive=True))


def write_version(folder: Path, version: Version) -> None:
    Path(folder).mkdir(parents=True, exist_ok=True)
    path = Path(folder) / VERSION_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(f"{version}\n", encoding="utf-8")
    tmp.replace(path)


def ensure_folder(folder: Path, name: str) -> None:
    """Make *folder* (``name``: "profile" or "jobs") if it is missing and stamp it with the current version when it
    holds no data yet (a missing folder, or one with only lock files): a folder this build creates carries its
    version from the first file. A folder with data and no file is v0.1.0's and is left for `upgrade_all`."""
    folder = Path(folder)
    if (folder / VERSION_FILE).exists():
        return
    folder.mkdir(parents=True, exist_ok=True)
    if all(child.name in _LOCK_FILES for child in folder.iterdir()):
        write_version(folder, current(name))


# --------------------------------------------------------------------------- #
# Backup and restore
# --------------------------------------------------------------------------- #
def _skip_locks(root: Path):
    """`copytree`'s ignore: the lock files at the top of *root* (held by this very process) are not data."""
    return lambda directory, names: [n for n in names if Path(directory) == root and n in _LOCK_FILES]


def _backup(folder: Path, backups_dir: Path, label: str, source: Version, target: Version) -> Path:
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
    """Bring *folder* to ``<app major>.<len(steps)>``: back it up, run the missing steps in order, write the version.

    The caller holds the lock and has checked the version is neither newer nor of an older major.
    Returns whether a step ran.

    Raises:
        _StepFailed: a step raised; the folder was restored from the backup and the version left as it was.
    """
    folder = Path(folder)
    have = read_version(folder) or UNVERSIONED
    want = Version(app_major(), len(steps))
    if compare(have, want) != "upgrade":
        return False
    backup = _backup(folder, Path(backups_dir), label, have, want)
    ran = ""
    try:
        for step in steps[have.n:]:
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


# What the last `upgrade_all` found: None, or {"state": "failed"|"newer"|"old_major"|"busy", "message": str}.
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
    """Read each folder's version without the lock: a refusal (newer, older major, garbled) or None."""
    for name, folder in folders:
        if not folder.is_dir():
            continue
        try:
            have = read_version(folder)
        except DataVersionError as exc:
            problem_log.failure("upgrade", str(exc))
            return _failed(f"reading {name}/{VERSION_FILE}")
        want = Version(app_major(), len(steps_of[name]))
        state = compare(have or UNVERSIONED, want)
        if state in ("newer", "old_major"):
            return {"state": state, "message": refusal_message(state, have or UNVERSIONED, want)}
    return None


def _behind(folders, steps_of) -> bool:
    return any(
        folder.is_dir()
        and compare(read_version(folder) or UNVERSIONED, Version(app_major(), len(steps_of[name]))) == "upgrade"
        for name, folder in folders
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

    A folder that does not exist is left alone. Newer, older-major or garbled data is refused and nothing is written. Called again
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


def run_at_start() -> dict | None:
    """What the MCP server and the CLI call before anything reads the data: `upgrade_all` on the data folder, then
    both folders made and stamped when missing, so a folder without a version file is only ever v0.1.0's data.

    Never raises: an unexpected error is a failed upgrade (logged), so the tools answer it and the user can report it.
    """
    try:
        state = upgrade_all()
        if state is None:  # both folders exist and are versioned from here on, whatever writes to them later
            ensure_folder(Path(workspace.PROFILE_DIR), "profile")
            ensure_folder(Path(workspace.JOBS_DIR), "jobs")
        return state
    except Exception as exc:  # noqa: BLE001 - startup must not die; the tools say what happened
        problem_log.failure("upgrade", f"{type(exc).__name__}: {exc}")
        return _set(_failed("start-up check"))


_logged: set[str] = set()


def _log_once(state: dict) -> None:
    if state["message"] not in _logged:
        _logged.add(state["message"])
        problem_log.failure("upgrade", state["message"])
