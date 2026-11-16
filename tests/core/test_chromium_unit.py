"""The pinned Chromium headless shell (#165): the pin, where it lives, how it is installed."""

from __future__ import annotations

import hashlib
import io
import stat
import sys
import zipfile
from pathlib import Path

import pytest

from door.core import chromium

KEYS = ("mac-arm64", "mac-x64", "linux64", "win64")


def test_the_pin_names_a_version_and_a_checksum_per_platform():
    pin = chromium.pin()
    assert pin["version"].count(".") == 3
    assert set(pin["platforms"]) == set(KEYS)
    for key in KEYS:
        sha = pin["platforms"][key]["sha256"]
        assert len(sha) == 64 and int(sha, 16) >= 0


def test_download_url_is_the_pinned_chrome_for_testing_zip():
    url = chromium.download_url("linux64")
    assert url == (
        "https://storage.googleapis.com/chrome-for-testing-public/"
        f"{chromium.pin()['version']}/linux64/chrome-headless-shell-linux64.zip"
    )


@pytest.mark.parametrize("system,machine,key", [
    ("Darwin", "arm64", "mac-arm64"),
    ("Darwin", "x86_64", "mac-x64"),
    ("Linux", "x86_64", "linux64"),
    ("Linux", "AMD64", "linux64"),
    ("Windows", "AMD64", "win64"),
    ("Windows", "ARM64", "win64"),   # the x64 shell runs under emulation
    ("Linux", "aarch64", None),
    ("FreeBSD", "amd64", None),
])
def test_platform_key(system, machine, key):
    assert chromium.platform_key(system, machine) == key


def test_exe_name_is_exe_on_windows_only():
    assert chromium.exe_name("win64") == "chrome-headless-shell.exe"
    assert chromium.exe_name("mac-arm64") == "chrome-headless-shell"


def _install_fake(root: Path, key: str) -> Path:
    exe = root / f"chrome-headless-shell-{key}" / chromium.exe_name(key)
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    return exe


def test_find_chromium_takes_the_bundled_one_first(tmp_path, monkeypatch):
    key = chromium.platform_key()
    if key is None:
        pytest.skip("no pinned shell for this machine")
    bundled = _install_fake(tmp_path / "bin" / "chromium", key)
    own = _install_fake(chromium.chromium_root(tmp_path / "home"), key)
    monkeypatch.setenv("DOOR_BIN", str(tmp_path / "bin"))
    assert chromium.find_chromium(home=tmp_path / "home") == str(bundled)
    monkeypatch.delenv("DOOR_BIN")
    assert chromium.find_chromium(home=tmp_path / "home") == str(own)


def test_find_chromium_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("DOOR_BIN", raising=False)
    assert chromium.find_chromium(home=tmp_path) is None


def test_chromium_root_is_per_user_and_per_version(tmp_path):
    assert chromium.chromium_root(tmp_path) == (
        tmp_path / ".local" / "share" / "door" / f"chromium-{chromium.pin()['version']}"
    )


# --------------------------------------------------------------------------- #
# install
# --------------------------------------------------------------------------- #

def _zip(key: str, extra: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"chrome-headless-shell-{key}/{chromium.exe_name(key)}", "binary")
        z.writestr(f"chrome-headless-shell-{key}/icudtl.dat", "data")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def pinned(monkeypatch):
    """Make the pin match a fake zip for the running platform."""
    key = "linux64" if not sys.platform.startswith("win") else "win64"
    monkeypatch.setattr(chromium, "platform_key", lambda *a, **k: key)
    real = chromium.pin()

    def make(data: bytes):
        monkeypatch.setattr(chromium, "pin", lambda: {
            "url": real["url"],
            "version": "1.2.3.4",
            "platforms": {key: {"sha256": hashlib.sha256(data).hexdigest()}},
        })
        return key

    return make


def test_install_unpacks_a_matching_zip(tmp_path, pinned):
    data = _zip("linux64")
    key = pinned(data)
    if key != "linux64":
        pytest.skip("fake zip is the linux one")
    urls = []
    chromium.install(tmp_path / "dest", fetch=lambda url, to: (urls.append(url), to.write_bytes(data)))
    exe = tmp_path / "dest" / "chrome-headless-shell-linux64" / "chrome-headless-shell"
    assert exe.read_text() == "binary"
    assert exe.stat().st_mode & stat.S_IXUSR
    assert urls == [chromium.download_url("linux64")]
    assert not list((tmp_path / "dest").glob("*.part"))


def test_install_refuses_a_wrong_checksum_and_leaves_nothing(tmp_path, pinned):
    key = pinned(_zip("linux64"))
    if key != "linux64":
        pytest.skip("fake zip is the linux one")
    with pytest.raises(chromium.ChromiumError, match="checksum"):
        chromium.install(tmp_path / "dest", fetch=lambda url, to: to.write_bytes(b"tampered"))
    assert not (tmp_path / "dest").exists() or not list((tmp_path / "dest").iterdir())


def test_install_refuses_an_entry_that_escapes(tmp_path, pinned):
    data = _zip("linux64", {"../evil.txt": b"x"})
    key = pinned(data)
    if key != "linux64":
        pytest.skip("fake zip is the linux one")
    with pytest.raises(chromium.ChromiumError, match="outside"):
        chromium.install(tmp_path / "dest", fetch=lambda url, to: to.write_bytes(data))
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path / "dest" / "chrome-headless-shell-linux64").exists()


def test_install_refuses_an_archive_without_the_shell(tmp_path, pinned):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("chrome-headless-shell-linux64/readme.txt", "no binary")
    data = buf.getvalue()
    key = pinned(data)
    if key != "linux64":
        pytest.skip("fake zip is the linux one")
    with pytest.raises(chromium.ChromiumError, match="no headless shell"):
        chromium.install(tmp_path / "dest", fetch=lambda url, to: to.write_bytes(data))
    assert not list((tmp_path / "dest").glob("*.part"))


def test_install_turns_a_bad_zip_into_a_chromium_error(tmp_path, pinned):
    data = b"this is not a zip"
    pinned(data)
    with pytest.raises(chromium.ChromiumError):
        chromium.install(tmp_path / "dest", fetch=lambda url, to: to.write_bytes(data))


def test_install_turns_a_failed_download_into_a_chromium_error(tmp_path, pinned):
    pinned(b"x")

    def fetch(url, to):
        raise OSError("connection reset")

    with pytest.raises(chromium.ChromiumError, match="connection reset"):
        chromium.install(tmp_path / "dest", fetch=fetch)
    assert not list((tmp_path / "dest").glob("*.part"))


def test_install_twice_downloads_once(tmp_path, pinned):
    data = _zip("linux64")
    key = pinned(data)
    if key != "linux64":
        pytest.skip("fake zip is the linux one")
    calls = []

    def fetch(url, to):
        calls.append(url)
        to.write_bytes(data)

    chromium.install(tmp_path / "dest", fetch=fetch)
    chromium.install(tmp_path / "dest", fetch=fetch)
    assert len(calls) == 1


def test_install_without_a_pinned_platform(tmp_path, monkeypatch):
    monkeypatch.setattr(chromium, "platform_key", lambda *a, **k: None)
    with pytest.raises(chromium.ChromiumError, match="no Chromium"):
        chromium.install(tmp_path / "dest", fetch=lambda url, to: None)


def test_main_exit_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(chromium, "install", lambda dest, **k: None)
    assert chromium.main(["--dest", str(tmp_path / "d")]) == 0

    def boom(dest, **k):
        raise chromium.ChromiumError("no network")

    monkeypatch.setattr(chromium, "install", boom)
    assert chromium.main(["--dest", str(tmp_path / "d")]) == 1
    assert "no network" in capsys.readouterr().err


def test_install_removes_the_other_versions_folders_and_leaves_the_rest(tmp_path, pinned):
    data = _zip("linux64")
    if pinned(data) != "linux64":
        pytest.skip("fake zip is the linux one")
    root = tmp_path / "door"
    old = root / "chromium-0.0.1.1"
    old.mkdir(parents=True)
    (old / "junk").write_text("x")
    other = root / "keep-me"
    other.mkdir()
    bundled = tmp_path / "bin" / "chromium"
    bundled.mkdir(parents=True)
    chromium.install(root / "chromium-1.2.3.4", fetch=lambda url, to: to.write_bytes(data))
    assert not old.exists()
    assert other.exists() and bundled.exists()
    assert (root / "chromium-1.2.3.4" / "chrome-headless-shell-linux64").is_dir()


def test_a_failed_install_keeps_the_older_folders(tmp_path, pinned):
    pinned(b"x")
    root = tmp_path / "door"
    old = root / "chromium-0.0.1.1"
    old.mkdir(parents=True)
    with pytest.raises(chromium.ChromiumError):
        chromium.install(root / "chromium-1.2.3.4", fetch=lambda url, to: to.write_bytes(b"bad"))
    assert old.exists()


def test_two_installs_racing_end_with_one_complete_folder(tmp_path, pinned):
    data = _zip("linux64")
    if pinned(data) != "linux64":
        pytest.skip("fake zip is the linux one")
    dest = tmp_path / "door" / "chromium-1.2.3.4"
    calls = []

    def fetch(url, to):
        calls.append(to)
        to.write_bytes(data)
        if len(calls) == 1:   # a second install runs through the whole of the first's download
            chromium.install(dest, fetch=fetch)

    chromium.install(dest, fetch=fetch)
    assert len(calls) == 2 and calls[0] != calls[1]
    exe = dest / "chrome-headless-shell-linux64" / "chrome-headless-shell"
    assert exe.read_text() == "binary"
    assert [p.name for p in dest.iterdir()] == ["chrome-headless-shell-linux64"]
