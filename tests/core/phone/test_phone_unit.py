"""The phone server under The other door's control (#444, #424): started, followed, paired and stopped for one data
folder, with a Cloudflare quick tunnel. Processes and HTTP are faked."""

import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime, timedelta

import pytest

from door import version as door_version
from door.core.phone import pairing
from door.core.phone import phone
from door.core.downloads import pinned as pinned_mod


class Proc:
    def __init__(self, pid):
        self.pid = pid


class World:
    """Fake processes: `spawn` records argv; a cloudflared writes its address to its log."""

    def __init__(self, tmp_path, *, tunnel_url="https://calm-river.trycloudflare.com", registers=True):
        self.spawned, self.killed = [], []
        self.alive = set()
        self.next_pid = 100
        self.tunnel_url = tunnel_url
        self.registers = registers
        self.checked = []

    def spawn(self, argv, *, log, env=None):
        self.next_pid += 1
        self.spawned.append({"argv": argv, "log": log, "env": env, "pid": self.next_pid})
        self.alive.add(self.next_pid)
        if "tunnel" in argv and self.tunnel_url:
            log.write_text(f"INF |  {self.tunnel_url}  |\n" + ("INF Registered tunnel connection connIndex=0\n" if self.registers else ""))
        return Proc(self.next_pid)

    def is_alive(self, pid):
        return pid in self.alive

    def kill(self, pid):
        self.killed.append(pid)
        self.alive.discard(pid)



def deps(world, tmp_path, **extra):
    return {
        "spawn": world.spawn, "is_alive": world.is_alive, "kill": world.kill,
        "answers": lambda url: True, "published": lambda host: True, "sleep": lambda s: None, "platform": "linux",
        "find_cloudflared": lambda: "/bin/cloudflared",
        "web_dir": tmp_path / "web", **extra,
    }


def test_try_it_starts_serve_and_a_quick_tunnel_and_remembers_them(tmp_path):
    w = World(tmp_path)
    out = phone.start(tmp_path, **deps(w, tmp_path))
    assert out["running"] is True and out["address"] == "https://calm-river.trycloudflare.com"
    assert set(out) == {"running", "devices", "web_built", "address", "port", "started_at", "outdated"}
    serve, tunnel = w.spawned[0], w.spawned[1]
    assert serve["argv"][-6:] == ["serve", "start", "--port", str(out["port"]), "--web", str(tmp_path / "web")]
    assert serve["env"]["DOOR_HOME"] == str(tmp_path)
    assert tunnel["argv"][:2] == ["/bin/cloudflared", "tunnel"] and f"http://127.0.0.1:{out['port']}" in tunnel["argv"]
    assert json.loads((tmp_path / ".serve" / "run.json").read_text())["address"] == out["address"]


def test_a_second_start_reuses_the_running_server(tmp_path):
    w = World(tmp_path)
    first = phone.start(tmp_path, **deps(w, tmp_path))
    again = phone.start(tmp_path, **deps(w, tmp_path))
    assert again["address"] == first["address"] and len(w.spawned) == 2


def test_a_dead_server_is_started_again(tmp_path):
    w = World(tmp_path)
    phone.start(tmp_path, **deps(w, tmp_path))
    w.alive.clear()  # the computer restarted
    assert phone.status(tmp_path, **deps(w, tmp_path))["running"] is False
    phone.start(tmp_path, **deps(w, tmp_path))
    assert len(w.spawned) == 4


def test_on_a_mac_the_computer_stays_awake_while_it_serves(tmp_path):
    w = World(tmp_path)
    phone.start(tmp_path, **deps(w, tmp_path, platform="darwin"))
    awake = [s for s in w.spawned if s["argv"][0] == "caffeinate"]
    assert awake and awake[0]["argv"] == ["caffeinate", "-i", "-w", str(w.spawned[0]["pid"])]


def test_a_tunnel_that_gives_no_address_is_an_error_and_nothing_is_left_running(tmp_path):
    w = World(tmp_path, tunnel_url=None)
    out = phone.start(tmp_path, **deps(w, tmp_path))
    assert "error" in out
    assert set(w.killed) == {s["pid"] for s in w.spawned}


def test_a_quick_tunnel_is_ready_when_cloudflare_registers_it_and_its_new_name_is_not_looked_up_here(tmp_path):
    w = World(tmp_path, registers=False)
    checked = []
    out = phone.start(tmp_path, **deps(w, tmp_path, answers=lambda url: checked.append(url) or True))
    assert "error" in out and "connect" in out["error"]
    # a brand-new name looked up too early is remembered as missing by this computer's resolver
    assert not any("trycloudflare" in u for u in checked)


def test_the_address_is_given_only_once_public_dns_knows_its_name(tmp_path):
    # a phone that looks the new name up too early gets "not found", and its resolver keeps that answer
    w = World(tmp_path)
    asked = []
    answers = iter([False, False, True])
    out = phone.start(tmp_path, **deps(w, tmp_path, published=lambda host: asked.append(host) or next(answers)))
    assert out["address"] == "https://calm-river.trycloudflare.com"
    assert asked == ["calm-river.trycloudflare.com"] * 3


def test_a_name_public_dns_cannot_confirm_is_given_after_a_bounded_wait(tmp_path):
    # a network that blocks the public DNS check: the tunnel itself works, so it goes on, well within the
    # app's five minutes for phone_start
    w = World(tmp_path)
    asked = []
    out = phone.start(tmp_path, **deps(w, tmp_path, published=lambda host: asked.append(host) or False))
    assert out["address"] == "https://calm-river.trycloudflare.com" and not w.killed
    assert len(asked) * (phone.PUBLISHED_TIMEOUT + 0.5) <= 120


def test_the_pairing_lives_as_long_as_the_tunnel(tmp_path):
    # a quick tunnel's address dies with it, and the phone's pairing is kept on that address
    w = World(tmp_path)
    phone.start(tmp_path, **deps(w, tmp_path))
    pairing.redeem(tmp_path, pairing.new_code(tmp_path, "My phone", strong=True))
    phone.stop(tmp_path, **deps(w, tmp_path))
    assert pairing.devices(tmp_path) == []
    # a phone left paired by a tunnel that died with the computer is forgotten by the next start
    pairing.redeem(tmp_path, pairing.new_code(tmp_path, "My phone", strong=True))
    phone.start(tmp_path, **deps(w, tmp_path))
    assert pairing.devices(tmp_path) == []


def test_stop_ends_everything_it_started(tmp_path):
    w = World(tmp_path)
    phone.start(tmp_path, **deps(w, tmp_path, platform="darwin"))
    out = phone.stop(tmp_path, **deps(w, tmp_path))
    assert out == {"stopped": True}
    assert set(w.killed) == {s["pid"] for s in w.spawned}
    assert not (tmp_path / ".serve" / "run.json").exists()
    assert phone.stop(tmp_path, **deps(w, tmp_path)) == {"stopped": False}


def test_pair_gives_a_qr_code_for_the_address_and_never_a_token(tmp_path):
    w = World(tmp_path)
    phone.start(tmp_path, **deps(w, tmp_path))
    real = phone.pair(tmp_path, "Ada's Pixel", **deps(w, tmp_path))
    assert real["qr_svg"].lstrip().startswith("<svg")
    encoded = []
    out = phone.pair(tmp_path, "Ada's Pixel", **deps(w, tmp_path, qr=lambda text: encoded.append(text) or "<svg/>"))
    # only the QR code: the code is never handed out as text (no link, no code field)
    assert set(out) == {"device", "qr_svg", "expires_at"}
    link = encoded[0]
    assert link.startswith("https://calm-river.trycloudflare.com/#pair=")
    code = link.split("#pair=")[1]
    assert len(code) == pairing.STRONG_LENGTH
    assert datetime.fromisoformat(out["expires_at"]) <= datetime.now(UTC) + timedelta(minutes=5, seconds=5)
    assert pairing.redeem(tmp_path, code) is not None


def test_the_qr_code_is_an_svg_an_image_tag_can_show(tmp_path):
    w = World(tmp_path)
    phone.start(tmp_path, **deps(w, tmp_path))
    assert 'xmlns="http://www.w3.org/2000/svg"' in phone.pair(tmp_path, "Pixel", **deps(w, tmp_path))["qr_svg"]


def test_a_tunnel_that_died_is_not_serving_and_starting_brings_all_of_it_back(tmp_path):
    w = World(tmp_path)
    first = phone.start(tmp_path, **deps(w, tmp_path))
    assert first["running"] is True
    w.alive.discard(w.spawned[1]["pid"])
    assert phone.status(tmp_path, **deps(w, tmp_path))["running"] is False
    assert "error" in phone.pair(tmp_path, "Pixel", **deps(w, tmp_path))  # no QR code for a dead address
    assert phone.start(tmp_path, **deps(w, tmp_path))["running"] is True
    assert w.spawned[0]["pid"] in w.killed  # the old server does not stay behind


def test_pair_without_a_running_server_says_so(tmp_path):
    w = World(tmp_path)
    assert "not serving" in phone.pair(tmp_path, "Pixel", **deps(w, tmp_path))["error"]


def test_status_lists_the_phones_and_where_it_serves(tmp_path):
    w = World(tmp_path)
    phone.start(tmp_path, **deps(w, tmp_path))
    pairing.redeem(tmp_path, pairing.new_code(tmp_path, "Pixel"))
    s = phone.status(tmp_path, **deps(w, tmp_path))
    assert s["running"] and s["address"] == "https://calm-river.trycloudflare.com"
    assert [d["device"] for d in s["devices"]] == ["Pixel"]
    assert s["web_built"] is False


def test_cloudflared_is_installed_from_its_pinned_release_and_checked(tmp_path, monkeypatch):
    payload = b"\x7fELF fake cloudflared"
    asset = phone.CLOUDFLARED["linux-x86_64"]

    def fetch(url, to):
        assert url.endswith(asset[0]) and phone.CLOUDFLARED_VERSION in url
        to.write_bytes(payload)

    monkeypatch.setattr(pinned_mod, "http_get", fetch)
    with pytest.raises(ValueError, match="checksum"):
        phone.install_cloudflared(tmp_path / "cloudflared-1", platform="linux", machine="x86_64")
    assert list((tmp_path / "cloudflared-1").iterdir()) == []   # no binary, no staging folder
    digest = hashlib.sha256(payload).hexdigest()
    pins = {"linux-x86_64": (asset[0], digest, digest)}
    path = phone.install_cloudflared(tmp_path / "cloudflared-1", platform="linux", machine="x86_64", pins=pins)
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
        phone.install_cloudflared(tmp_path, platform="darwin", machine="arm64", pins=pins)
    assert list(tmp_path.iterdir()) == []
    pins = {"darwin-arm64": (pins["darwin-arm64"][0], pins["darwin-arm64"][1], hashlib.sha256(b"macho").hexdigest())}
    path = phone.install_cloudflared(tmp_path, platform="darwin", machine="arm64", pins=pins)
    assert path.read_bytes() == b"macho"
    assert [p.name for p in tmp_path.iterdir()] == ["cloudflared"]


def test_installing_cloudflared_removes_older_versions_and_leaves_the_users_own(tmp_path, monkeypatch):
    digest = hashlib.sha256(b"new").hexdigest()
    pins = {"linux-x86_64": ("cloudflared-linux-amd64", digest, digest)}
    monkeypatch.setattr(pinned_mod, "http_get", lambda url, to: to.write_bytes(b"new"))
    (tmp_path / "cloudflared-0.1").mkdir()
    (tmp_path / "cloudflared-0.1" / "cloudflared").write_bytes(b"old")
    (tmp_path / "chromium-1").mkdir()
    phone.install_cloudflared(tmp_path / "cloudflared-2", platform="linux", machine="x86_64", pins=pins)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["chromium-1", "cloudflared-2"]


def test_a_cloudflared_system_without_a_pin_says_the_phone_is_not_available_there(tmp_path):
    with pytest.raises(ValueError, match="not available on this system.*linux-x86_64"):
        phone.install_cloudflared(tmp_path, platform="win32", machine="arm64")


def test_cloudflared_machines_map_to_their_pins():
    keys = {phone._system_key(p, m) for p, m in [("darwin", "x86_64"), ("linux", "aarch64"), ("linux", "armv7l"),
                                                  ("linux", "AMD64"), ("win32", "AMD64"), ("darwin", "arm64")]}
    assert keys == {"darwin-x86_64", "linux-arm64", "linux-arm", "linux-x86_64", "windows-x86_64", "darwin-arm64"}
    assert keys <= set(phone.CLOUDFLARED)


def test_remove_takes_a_phone_away(tmp_path):
    pairing.redeem(tmp_path, pairing.new_code(tmp_path, "Pixel"))
    assert phone.remove(tmp_path, "Pixel") == {"removed": "Pixel"}
    assert pairing.devices(tmp_path) == []
    assert "error" in phone.remove(tmp_path, "Pixel")


def _old_server(tmp_path, w, version="0.1.0"):
    w.alive.add(7)
    run = {"serve_pid": 7, "port": 8765, "address": "https://x", "started_at": "2026-01-01T00:00:00"}
    if version:
        run["version"] = version
    (tmp_path / ".serve").mkdir(exist_ok=True)
    (tmp_path / ".serve" / "run.json").write_text(json.dumps(run))


@pytest.mark.parametrize("version,outdated", [("0.1.0", True), (None, True), ("current", False)])
def test_status_says_a_live_server_of_another_version_is_outdated_and_changes_nothing(tmp_path, version, outdated):
    w = World(tmp_path)
    _old_server(tmp_path, w, door_version.VERSION if version == "current" else version)
    out = phone.status(tmp_path, **deps(w, tmp_path))
    assert out["running"] is True and out["outdated"] is outdated
    assert w.killed == [] and w.spawned == []


@pytest.mark.parametrize("version", ["0.1.0", None])
def test_start_replaces_a_running_server_of_another_version(tmp_path, version):
    w = World(tmp_path)
    _old_server(tmp_path, w, version)
    out = phone.start(tmp_path, **deps(w, tmp_path))
    assert 7 in w.killed and out["running"] is True and out["outdated"] is False
    assert json.loads((tmp_path / ".serve" / "run.json").read_text())["version"] == door_version.VERSION


def test_start_keeps_a_running_server_of_the_same_version(tmp_path):
    w = World(tmp_path)
    _old_server(tmp_path, w, door_version.VERSION)
    out = phone.start(tmp_path, **deps(w, tmp_path))
    assert out["running"] is True and w.killed == [] and w.spawned == []


def test_two_starts_at_once_spawn_one_server(tmp_path):
    import threading

    w = World(tmp_path)
    d = deps(w, tmp_path)
    gate = threading.Event()
    slow = d["answers"]

    def answers(url):
        gate.wait(0.3)  # the first start is still waiting for its server when the second one comes
        return slow(url)

    d["answers"] = answers
    out = []
    threads = [threading.Thread(target=lambda: out.append(phone.start(tmp_path, **d))) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len([s for s in w.spawned if "serve" in s["argv"]]) == 1


def test_pairing_a_second_phone_is_refused_until_the_first_is_unpaired(tmp_path):
    w = World(tmp_path)
    phone.start(tmp_path, **deps(w, tmp_path))
    pairing.redeem(tmp_path, pairing.new_code(tmp_path, "Pixel"))
    out = phone.pair(tmp_path, "Other", **deps(w, tmp_path))
    assert "unpair" in out["error"].lower() and "qr_svg" not in out
    phone.remove(tmp_path, "Pixel")
    assert "error" not in phone.pair(tmp_path, "Other", **deps(w, tmp_path, qr=lambda text: "<svg/>"))


def _own_cloudflared(tmp_path, payload=b"real"):
    """The home is tmp_path; the pin is the digest of `payload`."""
    folder = phone.cloudflared_root(tmp_path)
    folder.mkdir(parents=True)
    digest = hashlib.sha256(payload).hexdigest()
    return folder, {"linux-x86_64": ("cloudflared-linux-amd64", digest, digest)}


def _find(tmp_path, pins):
    return phone.find_cloudflared(home=tmp_path, pins=pins, platform="linux", machine="x86_64")


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


def test_start_downloads_the_pinned_cloudflared_when_no_checked_copy_is_found(tmp_path):
    world = World(tmp_path)
    installed = []
    d = deps(world, tmp_path, find_cloudflared=lambda: None,
             install_cloudflared=lambda: installed.append(1) or tmp_path / "cloudflared-x" / "cloudflared")
    out = phone.start(tmp_path, port=9000, **d)
    assert "error" not in out and installed == [1]
    tunnel = next(s for s in world.spawned if "tunnel" in s["argv"])
    assert tunnel["argv"][0] == str(tmp_path / "cloudflared-x" / "cloudflared")
