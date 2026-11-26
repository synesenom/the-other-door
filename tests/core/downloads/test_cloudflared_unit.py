import hashlib
import io
import tarfile

import pytest

from door.core.downloads import cloudflared
from door.core.downloads import pinned as pinned_mod


def test_cloudflared_is_installed_from_its_pinned_release_and_checked(tmp_path, monkeypatch):
    payload = b"\x7fELF fake cloudflared"
    asset = cloudflared.CLOUDFLARED["linux-x86_64"]

    def fetch(url, to):
        assert url.endswith(asset[0]) and cloudflared.CLOUDFLARED_VERSION in url
        to.write_bytes(payload)

    monkeypatch.setattr(pinned_mod, "http_get", fetch)
    with pytest.raises(ValueError, match="checksum"):
        cloudflared.install_cloudflared(tmp_path / "cloudflared-1", platform="linux", machine="x86_64")
    assert list((tmp_path / "cloudflared-1").iterdir()) == []   # no binary, no staging folder
    digest = hashlib.sha256(payload).hexdigest()
    pins = {"linux-x86_64": (asset[0], digest, digest)}
    path = cloudflared.install_cloudflared(tmp_path / "cloudflared-1", platform="linux", machine="x86_64", pins=pins)
    assert path.read_bytes() == payload and path.stat().st_mode & 0o111
    assert [p.name for p in path.parent.iterdir()] == ["cloudflared"]


def test_a_macos_cloudflared_comes_out_of_its_archive_and_is_checked(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"macho"
        info = tarfile.TarInfo("cloudflared")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    blob = buf.getvalue()

    monkeypatch.setattr(pinned_mod, "http_get", lambda url, to: to.write_bytes(blob))
    pins = {"darwin-arm64": ("cloudflared-darwin-arm64.tgz", hashlib.sha256(blob).hexdigest(), hashlib.sha256(b"stale").hexdigest())}
    with pytest.raises(ValueError, match="program"):   # a stale program pin fails at once
        cloudflared.install_cloudflared(tmp_path, platform="darwin", machine="arm64", pins=pins)
    assert list(tmp_path.iterdir()) == []
    pins = {"darwin-arm64": (pins["darwin-arm64"][0], pins["darwin-arm64"][1], hashlib.sha256(b"macho").hexdigest())}
    path = cloudflared.install_cloudflared(tmp_path, platform="darwin", machine="arm64", pins=pins)
    assert path.read_bytes() == b"macho"
    assert [p.name for p in tmp_path.iterdir()] == ["cloudflared"]


def test_a_cloudflared_system_without_a_pin_says_the_phone_is_not_available_there(tmp_path):
    with pytest.raises(ValueError, match="not available on this system.*linux-x86_64"):
        cloudflared.install_cloudflared(tmp_path, platform="linux", machine="riscv64")


def test_cloudflared_machines_map_to_their_pins():
    keys = {cloudflared._system_key(p, m) for p, m in [("darwin", "x86_64"), ("linux", "aarch64"), ("linux", "armv7l"),
                                                  ("linux", "AMD64"), ("win32", "AMD64"), ("win32", "ARM64"), ("darwin", "arm64")]}
    assert keys == {"darwin-x86_64", "linux-arm64", "linux-arm", "linux-x86_64", "windows-x86_64", "darwin-arm64"}   # Windows on ARM runs the x86-64 build
    assert keys <= set(cloudflared.CLOUDFLARED)


def _own_cloudflared(tmp_path, payload=b"real"):
    """The home is tmp_path; the pin is the digest of `payload`."""
    folder = cloudflared.cloudflared_root(tmp_path)
    folder.mkdir(parents=True)
    digest = hashlib.sha256(payload).hexdigest()
    return folder, {"linux-x86_64": ("cloudflared-linux-amd64", digest, digest)}


def _find(tmp_path, pins):
    return cloudflared.find_cloudflared(home=tmp_path, pins=pins, platform="linux", machine="x86_64")


def test_a_cloudflared_on_path_is_never_used(tmp_path, monkeypatch):
    _, pins = _own_cloudflared(tmp_path)
    on_path = tmp_path / "path"
    on_path.mkdir()
    fake = on_path / "cloudflared"
    fake.write_bytes(b"fake")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(on_path))
    assert _find(tmp_path, pins) is None


def test_a_downloaded_cloudflared_that_differs_from_the_pin_is_refused(tmp_path):
    folder, pins = _own_cloudflared(tmp_path)
    (folder / "cloudflared").write_bytes(b"tampered")
    assert _find(tmp_path, pins) is None


def test_a_downloaded_cloudflared_that_matches_the_pin_is_used(tmp_path):
    folder, pins = _own_cloudflared(tmp_path)
    (folder / "cloudflared").write_bytes(b"real")
    assert _find(tmp_path, pins) == str(folder / "cloudflared")
