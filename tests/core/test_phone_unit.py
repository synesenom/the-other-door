"""The phone server under The other door's control (#444, #424): started, followed, paired and stopped for one data
folder, with a Cloudflare quick tunnel or Tailscale. Processes, HTTP and the Tailscale CLI are faked."""

import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime, timedelta

import pytest

from door.core import pairing, phone


class Proc:
    def __init__(self, pid):
        self.pid = pid


class World:
    """Fake processes: `spawn` records argv; a cloudflared writes its address to its log."""

    def __init__(self, tmp_path, *, tunnel_url="https://calm-river.trycloudflare.com", registers=True):
        self.spawned, self.killed, self.ran = [], [], []
        self.alive = set()
        self.next_pid = 100
        self.tunnel_url = tunnel_url
        self.registers = registers
        self.checked = []
        self.tailscale = None  # {"state": ..., "dns": ..., "serve_out": ..., "serve_rc": ...}

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

    def run(self, argv, **kw):
        self.ran.append(argv)

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        r = R()
        if argv[1:3] == ["status", "--json"]:
            t = self.tailscale
            r.stdout = json.dumps({"BackendState": t["state"], "Self": {"DNSName": t["dns"]}})
        elif argv[1] == "serve":
            r.returncode = self.tailscale.get("serve_rc", 0)
            r.stdout = self.tailscale.get("serve_out", "")
        return r


def deps(world, tmp_path, **extra):
    return {
        "spawn": world.spawn, "is_alive": world.is_alive, "kill": world.kill, "run": world.run,
        "answers": lambda url: True, "sleep": lambda s: None, "platform": "linux",
        "find_cloudflared": lambda: "/bin/cloudflared", "find_tailscale": lambda: "/bin/tailscale" if world.tailscale else None,
        "web_dir": tmp_path / "web", **extra,
    }


def test_try_it_starts_serve_and_a_quick_tunnel_and_remembers_them(tmp_path):
    w = World(tmp_path)
    out = phone.start(tmp_path, "cloudflare", **deps(w, tmp_path))
    assert out["running"] is True and out["address"] == "https://calm-river.trycloudflare.com"
    assert out["connection"] == "cloudflare" and out["lasting"] is False
    serve, tunnel = w.spawned[0], w.spawned[1]
    assert serve["argv"][-6:] == ["serve", "start", "--port", str(out["port"]), "--web", str(tmp_path / "web")]
    assert serve["env"]["DOOR_HOME"] == str(tmp_path)
    assert tunnel["argv"][:2] == ["/bin/cloudflared", "tunnel"] and f"http://127.0.0.1:{out['port']}" in tunnel["argv"]
    assert json.loads((tmp_path / ".serve" / "run.json").read_text())["address"] == out["address"]


def test_a_second_start_reuses_the_running_server(tmp_path):
    w = World(tmp_path)
    first = phone.start(tmp_path, "cloudflare", **deps(w, tmp_path))
    again = phone.start(tmp_path, "cloudflare", **deps(w, tmp_path))
    assert again["address"] == first["address"] and len(w.spawned) == 2


def test_a_dead_server_is_started_again(tmp_path):
    w = World(tmp_path)
    phone.start(tmp_path, "cloudflare", **deps(w, tmp_path))
    w.alive.clear()  # the computer restarted
    assert phone.status(tmp_path, **deps(w, tmp_path))["running"] is False
    phone.start(tmp_path, "cloudflare", **deps(w, tmp_path))
    assert len(w.spawned) == 4


def test_on_a_mac_the_computer_stays_awake_while_it_serves(tmp_path):
    w = World(tmp_path)
    phone.start(tmp_path, "cloudflare", **deps(w, tmp_path, platform="darwin"))
    awake = [s for s in w.spawned if s["argv"][0] == "caffeinate"]
    assert awake and awake[0]["argv"] == ["caffeinate", "-i", "-w", str(w.spawned[0]["pid"])]


def test_a_tunnel_that_gives_no_address_is_an_error_and_nothing_is_left_running(tmp_path):
    w = World(tmp_path, tunnel_url=None)
    out = phone.start(tmp_path, "cloudflare", **deps(w, tmp_path))
    assert "error" in out
    assert set(w.killed) == {s["pid"] for s in w.spawned}


def test_a_quick_tunnel_is_ready_when_cloudflare_registers_it_and_its_new_name_is_not_looked_up_here(tmp_path):
    w = World(tmp_path, registers=False)
    checked = []
    out = phone.start(tmp_path, "cloudflare", **deps(w, tmp_path, answers=lambda url: checked.append(url) or True))
    assert "error" in out and "connect" in out["error"]
    # a brand-new name looked up too early is remembered as missing by this computer's resolver
    assert not any("trycloudflare" in u for u in checked)


def test_tailscale_missing_signed_out_or_without_https_says_what_to_do(tmp_path):
    w = World(tmp_path)
    assert phone.start(tmp_path, "tailscale", **deps(w, tmp_path))["needs"] == "install_tailscale"
    w.tailscale = {"state": "NeedsLogin", "dns": ""}
    assert phone.start(tmp_path, "tailscale", **deps(w, tmp_path))["needs"] == "sign_in_tailscale"
    w.tailscale = {"state": "Running", "dns": "mac.tail1234.ts.net.", "serve_rc": 1,
                   "serve_out": "HTTPS is not enabled. To enable, visit:\n\n         https://login.tailscale.com/f/serve?node=abc\n"}
    out = phone.start(tmp_path, "tailscale", **deps(w, tmp_path))
    assert out["needs"] == "enable_https" and out["link"] == "https://login.tailscale.com/f/serve?node=abc"


def test_tailscale_serves_at_the_computers_lasting_address(tmp_path):
    w = World(tmp_path)
    w.tailscale = {"state": "Running", "dns": "mac.tail1234.ts.net."}
    out = phone.start(tmp_path, "tailscale", **deps(w, tmp_path))
    assert out["address"] == "https://mac.tail1234.ts.net" and out["lasting"] is True
    assert ["/bin/tailscale", "serve", "--bg", str(out["port"])] in w.ran


def test_stop_ends_everything_it_started(tmp_path):
    w = World(tmp_path)
    w.tailscale = {"state": "Running", "dns": "mac.tail1234.ts.net."}
    phone.start(tmp_path, "tailscale", **deps(w, tmp_path, platform="darwin"))
    out = phone.stop(tmp_path, **deps(w, tmp_path))
    assert out == {"stopped": True}
    assert set(w.killed) == {s["pid"] for s in w.spawned}
    assert any(r[1:3] == ["serve", "--https=443"] and r[-1] == "off" for r in w.ran)
    assert not (tmp_path / ".serve" / "run.json").exists()
    assert phone.stop(tmp_path, **deps(w, tmp_path)) == {"stopped": False}


def test_pair_gives_a_qr_code_for_the_address_and_never_a_token(tmp_path):
    w = World(tmp_path)
    phone.start(tmp_path, "cloudflare", **deps(w, tmp_path))
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
    phone.start(tmp_path, "cloudflare", **deps(w, tmp_path))
    assert 'xmlns="http://www.w3.org/2000/svg"' in phone.pair(tmp_path, "Pixel", **deps(w, tmp_path))["qr_svg"]


def test_a_tunnel_that_died_is_not_serving_and_starting_brings_all_of_it_back(tmp_path):
    w = World(tmp_path)
    first = phone.start(tmp_path, "cloudflare", **deps(w, tmp_path))
    assert first["running"] is True
    w.alive.discard(w.spawned[1]["pid"])
    assert phone.status(tmp_path, **deps(w, tmp_path))["running"] is False
    assert "error" in phone.pair(tmp_path, "Pixel", **deps(w, tmp_path))  # no QR code for a dead address
    assert phone.start(tmp_path, "cloudflare", **deps(w, tmp_path))["running"] is True
    assert w.spawned[0]["pid"] in w.killed  # the old server does not stay behind


def test_after_a_restart_the_same_phone_pairs_again_under_its_name_and_only_the_new_token_works(tmp_path):
    w = World(tmp_path)
    phone.start(tmp_path, "cloudflare", **deps(w, tmp_path))
    codes = []
    qr = lambda text: codes.append(text.split("#pair=")[1]) or "<svg/>"  # noqa: E731
    phone.pair(tmp_path, "Pixel", **deps(w, tmp_path, qr=qr))
    _, old = pairing.redeem(tmp_path, codes[0])
    assert "error" not in phone.pair(tmp_path, "Pixel", **deps(w, tmp_path, qr=qr))
    assert pairing.verify(tmp_path, old) == "Pixel"  # until the new code is scanned, nothing changes
    _, new = pairing.redeem(tmp_path, codes[1])
    assert pairing.verify(tmp_path, new) == "Pixel" and pairing.verify(tmp_path, old) is None
    assert [d["device"] for d in pairing.devices(tmp_path)] == ["Pixel"]


def test_pair_without_a_running_server_says_so(tmp_path):
    w = World(tmp_path)
    assert "not serving" in phone.pair(tmp_path, "Pixel", **deps(w, tmp_path))["error"]


def test_status_lists_the_phones_and_the_connection(tmp_path):
    w = World(tmp_path)
    phone.start(tmp_path, "cloudflare", **deps(w, tmp_path))
    pairing.redeem(tmp_path, pairing.new_code(tmp_path, "Pixel"))
    s = phone.status(tmp_path, **deps(w, tmp_path))
    assert s["running"] and s["address"] == "https://calm-river.trycloudflare.com"
    assert [d["device"] for d in s["devices"]] == ["Pixel"]
    assert s["web_built"] is False


def test_cloudflared_is_installed_from_its_pinned_release_and_checked(tmp_path):
    payload = b"\x7fELF fake cloudflared"
    asset = phone.CLOUDFLARED["linux-x86_64"]

    def get(url, **kw):
        class R:
            content = payload
            status_code = 200

            def raise_for_status(self):
                pass

        assert url.endswith(asset[0]) and phone.CLOUDFLARED_VERSION in url
        return R()

    with pytest.raises(ValueError, match="checksum"):
        phone.install_cloudflared(tmp_path, get=get, platform="linux", machine="x86_64")
    pinned = {"linux-x86_64": (asset[0], hashlib.sha256(payload).hexdigest())}
    path = phone.install_cloudflared(tmp_path, get=get, platform="linux", machine="x86_64", pins=pinned)
    assert path.read_bytes() == payload and path.stat().st_mode & 0o111


def test_a_macos_cloudflared_comes_out_of_its_archive(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"macho"
        info = tarfile.TarInfo("cloudflared")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    blob = buf.getvalue()

    def get(url, **kw):
        class R:
            content = blob

            def raise_for_status(self):
                pass

        return R()

    pinned = {"darwin-arm64": ("cloudflared-darwin-arm64.tgz", hashlib.sha256(blob).hexdigest())}
    path = phone.install_cloudflared(tmp_path, get=get, platform="darwin", machine="arm64", pins=pinned)
    assert path.read_bytes() == b"macho"


def test_remove_takes_a_phone_away(tmp_path):
    pairing.redeem(tmp_path, pairing.new_code(tmp_path, "Pixel"))
    assert phone.remove(tmp_path, "Pixel") == {"removed": "Pixel"}
    assert pairing.devices(tmp_path) == []
    assert "error" in phone.remove(tmp_path, "Pixel")


def test_stopping_ends_each_process_group_not_just_its_first_process(monkeypatch):
    # Python on a Mac starts through a launcher: the server is a child in the launcher's group
    sent = []
    monkeypatch.setattr(phone.os, "killpg", lambda pgid, sig: sent.append(("group", pgid)), raising=False)
    monkeypatch.setattr(phone.os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(phone.sys, "platform", "darwin")
    phone._kill(4242)
    assert sent == [("group", 4242)]
