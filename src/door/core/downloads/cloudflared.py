"""The pinned cloudflared that carries the phone's tunnel (#444, #588).

Pinned per system by sha256, twice: the download and the program in it (the macOS download is an archive). It lives in its own
versioned folder (`cloudflared_root`), never one a user's own copy could be in, and `find_cloudflared` gives it only
when its sha256 is the pinned one, so a changed file is downloaded again (`install_cloudflared`), never run.
"""

from __future__ import annotations

import sys
import tarfile
from pathlib import Path

from door.core import utils
from door.core.downloads import pinned

CLOUDFLARED_VERSION = "2026.10.6"
# The release's own digests (github.com/cloudflare/cloudflared/releases): (asset, sha256 of the download, sha256 of
# the program in it; the same when the download is the program), checked before anything runs.
CLOUDFLARED = {
    "darwin-arm64": ("cloudflared-darwin-arm64.tgz", "ea1e5105d35bbe16cee5b2f7b4742059ada341fbd35938ed827c24b85efa51c8",
                     "380451015c3676789adc4200f43757e950e7173b920b0094e272e8bea59d7927"),
    "darwin-x86_64": ("cloudflared-darwin-amd64.tgz", "6c04a13835ca5ff29a0c6f58d17d1f3956aad1b7df1631f5b5efbc06269deded",
                      "2b74a9a6b9e5161dbf79a77c2fcc6337cd7e9d2b23eee9d1b6635ecb17608589"),
    "linux-x86_64": ("cloudflared-linux-amd64", "1d356dac769d0dbf62ebe588c4034824bbff98d5790c2f844cc99e0e2f57462d",
                     "1d356dac769d0dbf62ebe588c4034824bbff98d5790c2f844cc99e0e2f57462d"),
    "linux-arm64": ("cloudflared-linux-arm64", "0ae0e179475b2c77651a718d2b376e0151f4fca5954702a84f02843a4d5fcac0",
                    "0ae0e179475b2c77651a718d2b376e0151f4fca5954702a84f02843a4d5fcac0"),
    "linux-arm": ("cloudflared-linux-arm", "276b306200086dee90c10954fa37cf26a6664052fa750e04b1831f69158cd2f6",
                  "276b306200086dee90c10954fa37cf26a6664052fa750e04b1831f69158cd2f6"),
    "windows-x86_64": ("cloudflared-windows-amd64.exe", "d521b3bf68982165f0d06d76732f22d9a105ef057ff3ae4c0986f3a23190950f",
                       "d521b3bf68982165f0d06d76732f22d9a105ef057ff3ae4c0986f3a23190950f"),
}


def cloudflared_root(home: Path | None = None) -> Path:
    """Where the pinned cloudflared lives: a folder of The other door's own, one per pinned version, so a
    cloudflared the user installed themselves is never run or overwritten."""
    return pinned.folder("cloudflared", CLOUDFLARED_VERSION, home)


def find_cloudflared(*, home: Path | None = None, pins: dict = CLOUDFLARED, platform: str | None = None,
                     machine: str | None = None) -> str | None:
    """The pinned cloudflared of `cloudflared_root` if its sha256 is the pinned one, else None (`start` then
    downloads it). Any other cloudflared, PATH's included, is never run."""
    key = _system_key(platform, machine)
    if key not in pins:
        return None
    path = cloudflared_root(home) / _program_name(key)
    return str(path) if path.is_file() and pinned.sha256(path) == pins[key][2] else None


def _arch(machine: str) -> str:
    machine = machine.lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    return "arm" if machine.startswith("arm") else machine


def _system_key(platform: str | None = None, machine: str | None = None) -> str:
    import platform as platform_mod

    system = {"darwin": "darwin", "win32": "windows"}.get(platform or sys.platform, "linux")
    arch = _arch(machine or platform_mod.machine())
    return f"{system}-{'x86_64' if system == 'windows' and arch == 'arm64' else arch}"  # Windows on ARM runs the x86-64 build


def _program_name(key: str) -> str:
    return "cloudflared.exe" if key.startswith("windows-") else "cloudflared"


def install_cloudflared(dest: Path | None = None, *, platform: str | None = None, machine: str | None = None,
                        pins: dict = CLOUDFLARED) -> Path:
    """Download the pinned cloudflared for this system, check the download and the program in it against their
    digests, put it in `dest` (`cloudflared_root`, older versions' folders removed)."""
    key = _system_key(platform, machine)
    if key not in pins:
        raise ValueError(f"The phone is not available on this system ({key}); it works on {', '.join(sorted(pins))}.")
    asset, digest, program_digest = pins[key]
    url = f"https://github.com/cloudflare/cloudflared/releases/download/{CLOUDFLARED_VERSION}/{asset}"
    dest = Path(dest or cloudflared_root())
    target = dest / _program_name(key)
    with utils.staging(dest, ".cloudflared.") as staging:
        pinned.download([(url, asset, digest)], staging)
        staged = staging / target.name
        if asset.endswith(".tgz"):
            with tarfile.open(staging / asset, mode="r:gz") as tar:
                member = next(m for m in tar.getmembers() if Path(m.name).name == "cloudflared" and m.isfile())
                staged.write_bytes(tar.extractfile(member).read())
        else:
            (staging / asset).rename(staged)
        if pinned.sha256(staged) != program_digest:
            raise ValueError(f"the cloudflared program does not match its pinned checksum; nothing was installed ({url})")
        staged.chmod(0o755)
        staged.replace(target)
    pinned.remove_other_versions(dest, "cloudflared")
    return target
