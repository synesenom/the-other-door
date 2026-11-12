"""`./door serve` (#302): run the HTTP server for this data folder; pair, list and unpair phones."""

from click.testing import CliRunner

from door.cli import cli
from door.commands import serve as serve_cmd
from door.core import pairing, workspace


def run(*args):
    return CliRunner().invoke(cli, ["serve", *args], catch_exceptions=False)


def test_pair_prints_a_code_and_with_a_url_a_link_and_qr(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    r = run("pair", "--device", "Anna's Pixel")
    assert r.exit_code == 0
    code = next(w for w in r.output.split() if len(w) == 9 and w[4] == "-")
    assert "10 minutes" in r.output
    assert pairing.redeem(tmp_path, code) is not None

    r = run("pair", "--device", "Tablet", "--url", "https://anna.example.net/")
    assert "https://anna.example.net/#pair=" in r.output
    assert "█" in r.output  # the QR code, for the phone's camera


def test_pair_refuses_a_name_already_paired(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    pairing.redeem(tmp_path, pairing.new_code(tmp_path, "Pixel"))
    r = run("pair", "--device", "Pixel")
    assert r.exit_code == 1 and "already paired" in r.output


def test_devices_and_unpair(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    assert "No phone is paired" in run("devices").output
    pairing.redeem(tmp_path, pairing.new_code(tmp_path, "Pixel"))
    assert "Pixel" in run("devices").output
    r = run("unpair", "Pixel")
    assert r.exit_code == 0 and "Pixel" in r.output
    assert run("unpair", "Pixel").exit_code == 1


def test_serve_binds_to_this_machine_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    seen = {}
    monkeypatch.setattr(serve_cmd, "_run_server", lambda app, host, port: seen.update(host=host, port=port, app=app))
    r = run()
    assert r.exit_code == 0, r.output
    assert seen["host"] == "127.0.0.1" and seen["port"] == 8765
    assert "http://127.0.0.1:8765" in r.output
    assert seen["app"].state.home == tmp_path.resolve()

    run("start", "--host", "0.0.0.0", "--port", "9001")
    assert seen["host"] == "0.0.0.0" and seen["port"] == 9001


def test_the_core_says_where_and_whether_the_web_app_is_built(tmp_path):
    web = tmp_path / "web"
    out = serve_cmd._serve_core(home=tmp_path, host="127.0.0.1", port=8765, name=None, web_dir=web)
    assert out["web_built"] is False and out["url"] == "http://127.0.0.1:8765"
    web.mkdir()
    (web / "index.html").write_text("x")
    out = serve_cmd._serve_core(home=tmp_path, host="127.0.0.1", port=8765, name="Anna", web_dir=web)
    assert out["web_built"] is True and out["name"] == "Anna"


def test_serve_registers_its_home_and_refuses_another_persons_port(tmp_path, monkeypatch):
    from door.core import instances

    monkeypatch.setattr(serve_cmd, "_run_server", lambda app, host, port: None)
    anna, ben = tmp_path / "anna", tmp_path / "ben"
    monkeypatch.setattr(workspace, "HOME", anna)
    assert run("start", "--name", "Anna").exit_code == 0
    assert instances.read()[str(anna.resolve())]["port"] == 8765
    monkeypatch.setattr(workspace, "HOME", ben)
    r = CliRunner().invoke(cli, ["serve", "start", "--name", "Ben"])
    assert r.exit_code == 1 and "port 8765" in r.output


def test_install_agent_and_uninstall_agent(tmp_path, monkeypatch):
    from door.core import launch_agent

    monkeypatch.setattr(workspace, "HOME", tmp_path)
    seen = {}
    monkeypatch.setattr(launch_agent, "install", lambda **kw: seen.update(kw) or tmp_path / "agent.plist")
    monkeypatch.setattr(launch_agent, "uninstall", lambda **kw: tmp_path / "agent.plist")
    r = run("install-agent", "--port", "8766", "--name", "Anna")
    assert r.exit_code == 0 and "agent.plist" in r.output
    assert seen["port"] == 8766 and seen["name"] == "Anna" and seen["home"] == tmp_path
    assert run("uninstall-agent", "--name", "Anna").exit_code == 0
