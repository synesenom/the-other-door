"""The pinned Chromium headless shell that prints CVs (#165).

One data file, `chromium_pin.json`, names the Chrome for Testing version and each platform's
sha256; this module and the app's bundle scripts read it, so there is one pin. The shell is
found in the packaged app's `$DOOR_BIN/chromium/`, else in a per-user folder that
`python -m door.core.chromium --dest <folder>` fills (what `doctor --fix` runs): downloaded,
checked against the pin, unpacked, never partly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform as _platform
import shutil
import stat
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

_PIN = Path(__file__).with_name("chromium_pin.json")


class ChromiumError(Exception):
    pass


def pin() -> dict:
    return json.loads(_PIN.read_text(encoding="utf-8"))


def platform_key(system: str | None = None, machine: str | None = None) -> str | None:
    """Chrome for Testing's name for this machine, or None where it ships no headless shell.

    Windows on ARM runs the win64 shell under emulation.
    """
    system = system if system is not None else _platform.system()
    machine = (machine if machine is not None else _platform.machine()).lower()
    if system == "Darwin":
        return {"arm64": "mac-arm64", "aarch64": "mac-arm64", "x86_64": "mac-x64", "amd64": "mac-x64"}.get(machine)
    if system == "Linux":
        return "linux64" if machine in ("x86_64", "amd64") else None
    if system == "Windows":
        return "win64" if machine in ("amd64", "x86_64", "arm64") else None
    return None


def exe_name(key: str) -> str:
    return "chrome-headless-shell.exe" if key == "win64" else "chrome-headless-shell"


def download_url(key: str) -> str:
    p = pin()
    return p["url"].format(version=p["version"], key=key)


def chromium_root(home: Path | None = None) -> Path:
    """Where `doctor --fix` puts the shell: user-owned, one folder per pinned version."""
    base = Path(home) if home is not None else Path.home()
    return base / ".local" / "share" / "door" / f"chromium-{pin()['version']}"


def find_chromium(home: Path | None = None) -> str | None:
    """The shell: the packaged app's own (`$DOOR_BIN/chromium`), else the per-user install."""
    key = platform_key()
    if key is None:
        return None
    relative = Path(f"chrome-headless-shell-{key}") / exe_name(key)
    roots = []
    bundled = os.environ.get("DOOR_BIN")
    if bundled:
        roots.append(Path(bundled) / "chromium")
    roots.append(chromium_root(home))
    for root in roots:
        if (root / relative).is_file():
            return str(root / relative)
    return None


def http_get(url: str, to: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, open(to, "wb") as out:  # noqa: S310 - https, pinned
        shutil.copyfileobj(response, out)


def _remove_other_versions(dest: Path) -> None:
    """Drop the older `chromium-*` folders beside `dest`, only where `dest` is one of them."""
    if not dest.name.startswith("chromium-"):
        return
    for other in dest.parent.glob("chromium-*"):
        if other != dest and other.is_dir():
            shutil.rmtree(other, ignore_errors=True)


# An install takes minutes; a staging folder older than this was left by one that was killed.
STALE_PART_SECONDS = 3600


def _sweep_stale_parts(dest: Path) -> None:
    """Remove the staging folders a killed install left in `dest`, never one still in use."""
    cutoff = time.time() - STALE_PART_SECONDS
    for part in dest.glob("*.part"):
        if part.is_dir() and part.stat().st_mtime < cutoff:
            shutil.rmtree(part, ignore_errors=True)


def install(dest: Path, fetch=http_get) -> None:
    """Download the pinned zip, check its sha256 and unpack it into `dest` (a no-op when there)."""
    key = platform_key()
    if key is None:
        raise ChromiumError(f"no Chromium headless shell is pinned for {_platform.system()} {_platform.machine()}")
    dest = Path(dest)
    folder = dest / f"chrome-headless-shell-{key}"
    if (folder / exe_name(key)).is_file():
        _remove_other_versions(dest)
        return
    dest.mkdir(parents=True, exist_ok=True)
    _sweep_stale_parts(dest)
    # Names unique to this process, so two installs never share a half-written file.
    staging = Path(tempfile.mkdtemp(prefix=f"{folder.name}.", suffix=".part", dir=dest))
    part = staging / "download.zip"
    try:
        fetch(download_url(key), part)
        digest = hashlib.sha256(part.read_bytes()).hexdigest()
        if digest != pin()["platforms"][key]["sha256"]:
            raise ChromiumError("the download does not match the pinned checksum; nothing was installed")
        with zipfile.ZipFile(part) as z:
            for name in z.namelist():
                target = (staging / name).resolve()
                if not target.is_relative_to(staging.resolve()):
                    raise ChromiumError(f"the archive has an entry outside its folder: {name}")
            z.extractall(staging)
        exe = staging / folder.name / exe_name(key)
        if not exe.is_file():
            raise ChromiumError("the archive has no headless shell in it")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        try:
            (staging / folder.name).rename(folder)
        except OSError:
            if not (folder / exe_name(key)).is_file():   # else another install finished first: keep it
                raise
        _remove_other_versions(dest)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ChromiumError(str(exc)) from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m door.core.chromium")
    parser.add_argument("--dest", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        install(args.dest)
    except ChromiumError as exc:
        sys.stderr.write(f"Chromium: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
